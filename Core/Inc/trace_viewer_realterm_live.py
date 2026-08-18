#!/usr/bin/env python3
"""Trace Viewer for STM32 binary captures.

Frame format:
    AA 55 + <I H B B I

Usage:
    python trace_viewer.py trace.h capture.bin
    python trace_viewer.py trace.h capture.bin --clock 216000000U
    python trace_viewer.py trace.h capture.bin --csv events.csv --no-gui
"""

from __future__ import annotations

import argparse
import csv
import re
import struct
import sys
import queue
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

SYNC = b"\xAA\x55"
RECORD_FORMAT = "<IHBBI"
RECORD_SIZE = struct.calcsize(RECORD_FORMAT)
FRAME_SIZE = len(SYNC) + RECORD_SIZE
UINT32_MODULO = 1 << 32
DEFAULT_CLOCK_HZ = 216_000_000
KNOWN_FLAGS_MASK = 0x01


@dataclass(frozen=True, slots=True)
class TraceEvent:
    number: int
    file_offset: int
    timestamp_raw: int
    timestamp_extended: int
    event_id: int
    context_id: int
    flags: int
    value: int
    event_name: str
    time_seconds: float
    delta_cycles: int
    delta_seconds: float

    @property
    def is_isr(self) -> bool:
        return bool(self.flags & 0x01)

    @property
    def unknown_flags(self) -> int:
        return self.flags & ~KNOWN_FLAGS_MASK


@dataclass(frozen=True, slots=True)
class ParseStats:
    bytes_total: int
    frames: int
    discarded_bytes: int
    trailing_bytes: int
    timestamp_wraps: int


def parse_clock(value: str) -> int:
    """Accept values such as 216000000, 216000000U, 216MHz and 0x0CDFE600UL."""
    text = value.strip().replace("_", "")
    mhz_match = re.fullmatch(r"(?i)(\d+(?:\.\d+)?)\s*mhz", text)
    if mhz_match:
        result = int(float(mhz_match.group(1)) * 1_000_000)
    else:
        text = re.sub(r"(?i)[uUlL]+$", "", text)
        result = int(text, 0)
    if result <= 0:
        raise argparse.ArgumentTypeError("Zegar musi być większy od zera")
    return result


def strip_c_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return re.sub(r"//.*?$", "", text, flags=re.M)


def parse_c_integer(expression: str, known: dict[str, int]) -> int | None:
    expression = expression.strip()
    expression = re.sub(r"(?i)\b(0x[0-9a-f]+|\d+)[uUlL]+\b", r"\1", expression)
    expression = re.sub(r"\([^()]*(?:int|char|short|long|Trace\w*)[^()]*\)", "", expression)
    for name, value in sorted(known.items(), key=lambda item: -len(item[0])):
        expression = re.sub(rf"\b{re.escape(name)}\b", str(value), expression)
    if not re.fullmatch(r"[0-9a-fA-FxX\s()+\-*/%<>&|~^]+", expression):
        return None
    try:
        return int(eval(expression, {"__builtins__": {}}, {}))
    except Exception:
        return None


def parse_trace_header(path: Path) -> dict[int, str]:
    """Extract numeric TRACE_* constants from C enums and #defines."""
    text = strip_c_comments(path.read_text(encoding="utf-8", errors="replace"))
    symbols: dict[str, int] = {}

    for name, expression in re.findall(
        r"^\s*#\s*define\s+(TRACE_[A-Za-z0-9_]+)\s+([^\r\n]+)", text, re.M
    ):
        value = parse_c_integer(expression, symbols)
        if value is not None:
            symbols[name] = value

    for body in re.findall(r"\btypedef\s+enum\b[^\{]*\{(.*?)\}\s*\w*\s*;", text, re.S):
        next_value = 0
        for item in body.split(","):
            item = item.strip()
            if not item:
                continue
            match = re.match(r"^(TRACE_[A-Za-z0-9_]+)\s*(?:=\s*(.+))?$", item, re.S)
            if not match:
                continue
            name, expression = match.groups()
            if expression is not None:
                value = parse_c_integer(expression, symbols)
                if value is None:
                    continue
                next_value = value
            symbols[name] = next_value
            next_value += 1

    # Constants related to framing/configuration are not event names.
    ignored = {
        "TRACE_UART_HEADER_0",
        "TRACE_UART_HEADER_1",
        "TRACE_BUFFER_SIZE",
    }
    result: dict[int, str] = {}
    for name, value in symbols.items():
        if name not in ignored and 0 <= value <= 0xFFFF:
            result.setdefault(value, name)
    return result


def parse_capture(data: bytes, names: dict[int, str], clock_hz: int) -> tuple[list[TraceEvent], ParseStats]:
    events: list[TraceEvent] = []
    cursor = 0
    discarded = 0
    wraps = 0
    previous_raw: int | None = None
    previous_extended: int | None = None

    while True:
        sync_at = data.find(SYNC, cursor)
        if sync_at < 0:
            trailing = len(data) - cursor
            discarded += trailing
            break

        discarded += sync_at - cursor
        if sync_at + FRAME_SIZE > len(data):
            trailing = len(data) - sync_at
            break

        timestamp, event_id, context_id, flags, value = struct.unpack_from(
            RECORD_FORMAT, data, sync_at + len(SYNC)
        )

        if previous_raw is not None and timestamp < previous_raw:
            wraps += 1
        extended = timestamp + wraps * UINT32_MODULO
        delta_cycles = 0 if previous_extended is None else extended - previous_extended

        number = len(events) + 1
        events.append(
            TraceEvent(
                number=number,
                file_offset=sync_at,
                timestamp_raw=timestamp,
                timestamp_extended=extended,
                event_id=event_id,
                context_id=context_id,
                flags=flags,
                value=value,
                event_name=names.get(event_id, f"UNKNOWN_{event_id}"),
                time_seconds=extended / clock_hz,
                delta_cycles=delta_cycles,
                delta_seconds=delta_cycles / clock_hz,
            )
        )
        previous_raw = timestamp
        previous_extended = extended
        cursor = sync_at + FRAME_SIZE

    stats = ParseStats(
        bytes_total=len(data),
        frames=len(events),
        discarded_bytes=discarded,
        trailing_bytes=trailing,
        timestamp_wraps=wraps,
    )
    return events, stats


class StreamParser:
    """Incremental parser for a growing binary capture stream."""

    def __init__(self, names: dict[int, str], clock_hz: int) -> None:
        self.names = names
        self.clock_hz = clock_hz
        self.buffer = bytearray()
        self.stream_offset = 0
        self.event_number = 0
        self.previous_raw: int | None = None
        self.previous_extended: int | None = None
        self.wraps = 0
        self.discarded = 0
        self.bytes_total = 0

    def feed(self, data: bytes) -> list[TraceEvent]:
        """Add bytes and return only newly decoded events."""
        if not data:
            return []

        self.bytes_total += len(data)
        self.buffer.extend(data)
        events: list[TraceEvent] = []

        while True:
            sync_at = self.buffer.find(SYNC)

            if sync_at < 0:
                # Keep one trailing 0xAA because it can begin AA 55 in the next chunk.
                keep = 1 if self.buffer.endswith(SYNC[:1]) else 0
                discard_count = len(self.buffer) - keep
                if discard_count > 0:
                    del self.buffer[:discard_count]
                    self.stream_offset += discard_count
                    self.discarded += discard_count
                break

            if sync_at > 0:
                del self.buffer[:sync_at]
                self.stream_offset += sync_at
                self.discarded += sync_at

            if len(self.buffer) < FRAME_SIZE:
                break

            timestamp, event_id, context_id, flags, value = struct.unpack_from(
                RECORD_FORMAT, self.buffer, len(SYNC)
            )
            frame_offset = self.stream_offset
            del self.buffer[:FRAME_SIZE]
            self.stream_offset += FRAME_SIZE

            if self.previous_raw is not None and timestamp < self.previous_raw:
                self.wraps += 1

            extended = timestamp + self.wraps * UINT32_MODULO
            delta_cycles = (
                0
                if self.previous_extended is None
                else extended - self.previous_extended
            )
            self.event_number += 1
            event = TraceEvent(
                number=self.event_number,
                file_offset=frame_offset,
                timestamp_raw=timestamp,
                timestamp_extended=extended,
                event_id=event_id,
                context_id=context_id,
                flags=flags,
                value=value,
                event_name=self.names.get(event_id, f"UNKNOWN_{event_id}"),
                time_seconds=extended / self.clock_hz,
                delta_cycles=delta_cycles,
                delta_seconds=delta_cycles / self.clock_hz,
            )
            events.append(event)
            self.previous_raw = timestamp
            self.previous_extended = extended

        return events

    def stats(self) -> ParseStats:
        return ParseStats(
            bytes_total=self.bytes_total,
            frames=self.event_number,
            discarded_bytes=self.discarded,
            trailing_bytes=len(self.buffer),
            timestamp_wraps=self.wraps,
        )


def follow_capture_file(
    path: Path,
    output_queue: queue.Queue[tuple[str, object]],
    stop_event: threading.Event,
    poll_interval: float,
) -> None:
    """Read bytes appended by RealTerm and send them to the GUI thread."""
    position = 0
    output_queue.put(("status", f"Oczekiwanie na plik RealTerm: {path}"))

    try:
        while not stop_event.is_set():
            if not path.exists():
                time.sleep(poll_interval)
                continue

            size = path.stat().st_size
            if size < position:
                # RealTerm Start Overwrite or capture restart truncated the file.
                position = 0
                output_queue.put(("reset", "Plik capture.bin został wyzerowany."))

            if size > position:
                with path.open("rb") as stream:
                    stream.seek(position)
                    data = stream.read(size - position)
                position += len(data)
                if data:
                    output_queue.put(("data", data))
            else:
                time.sleep(poll_interval)
    except OSError as exc:
        output_queue.put(("error", f"Błąd śledzenia pliku: {exc}"))
    finally:
        output_queue.put(("closed", None))


def write_csv(path: Path, events: Iterable[TraceEvent], clock_hz: int) -> None:
    with path.open("w", newline="", encoding="utf-8-sig") as stream:
        writer = csv.writer(stream, delimiter=";")
        writer.writerow([
            "number", "offset", "timestamp_raw", "timestamp_extended",
            "time_s", "time_ms", "delta_cycles", "delta_us", "event_id",
            "event_name", "context_id", "flags", "isr", "value", "clock_hz"
        ])
        for event in events:
            writer.writerow([
                event.number,
                f"0x{event.file_offset:08X}",
                event.timestamp_raw,
                event.timestamp_extended,
                f"{event.time_seconds:.9f}",
                f"{event.time_seconds * 1000:.6f}",
                event.delta_cycles,
                f"{event.delta_seconds * 1_000_000:.3f}",
                event.event_id,
                event.event_name,
                event.context_id,
                f"0x{event.flags:02X}",
                int(event.is_isr),
                event.value,
                clock_hz,
            ])


def show_file_gui(events: list[TraceEvent], stats: ParseStats, names_count: int, clock_hz: int,
             header_path: Path, capture_path: Path) -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise RuntimeError("Brak tkinter. Użyj opcji --no-gui lub doinstaluj tkinter.") from exc

    root = tk.Tk()
    root.title(f"Trace Viewer - {capture_path.name}")
    root.geometry("1450x820")
    root.minsize(900, 500)

    filter_event = tk.StringVar()
    filter_context = tk.StringVar()
    only_isr = tk.BooleanVar(value=False)
    status = tk.StringVar()

    toolbar = ttk.Frame(root, padding=8)
    toolbar.pack(fill="x")
    ttk.Label(toolbar, text="Event ID/nazwa:").pack(side="left")
    ttk.Entry(toolbar, textvariable=filter_event, width=20).pack(side="left", padx=(4, 12))
    ttk.Label(toolbar, text="Context ID:").pack(side="left")
    ttk.Entry(toolbar, textvariable=filter_context, width=10).pack(side="left", padx=(4, 12))
    ttk.Checkbutton(toolbar, text="Tylko ISR", variable=only_isr).pack(side="left", padx=(0, 12))

    columns = (
        "nr", "offset", "time_ms", "delta_us", "timestamp", "event_id",
        "event_name", "context", "flags", "isr", "value"
    )
    tree_frame = ttk.Frame(root)
    tree_frame.pack(fill="both", expand=True, padx=8)
    tree = ttk.Treeview(tree_frame, columns=columns, show="headings")
    headings = {
        "nr": "Nr", "offset": "Offset", "time_ms": "Czas [ms]",
        "delta_us": "Delta [us]", "timestamp": "Timestamp", "event_id": "Event ID",
        "event_name": "Nazwa zdarzenia", "context": "Context", "flags": "Flags",
        "isr": "ISR", "value": "Value"
    }
    widths = {
        "nr": 65, "offset": 100, "time_ms": 130, "delta_us": 120,
        "timestamp": 120, "event_id": 80, "event_name": 230, "context": 80,
        "flags": 70, "isr": 55, "value": 120
    }
    for column in columns:
        tree.heading(column, text=headings[column])
        tree.column(column, width=widths[column], anchor="center" if column != "event_name" else "w")
    y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=tree.yview)
    x_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    tree_frame.rowconfigure(0, weight=1)
    tree_frame.columnconfigure(0, weight=1)
    tree.tag_configure("isr", background="#FFF2CC")
    tree.tag_configure("warning", background="#F4CCCC")

    filtered_events: list[TraceEvent] = []

    def matches(event: TraceEvent) -> bool:
        event_query = filter_event.get().strip().lower()
        context_query = filter_context.get().strip()
        if event_query and event_query not in str(event.event_id) and event_query not in event.event_name.lower():
            return False
        if context_query:
            try:
                if event.context_id != int(context_query, 0):
                    return False
            except ValueError:
                return False
        return not only_isr.get() or event.is_isr

    def refresh(*_args: object) -> None:
        nonlocal filtered_events
        tree.delete(*tree.get_children())
        filtered_events = [event for event in events if matches(event)]
        for event in filtered_events:
            tag = "warning" if event.unknown_flags else ("isr" if event.is_isr else "")
            tree.insert("", "end", values=(
                event.number,
                f"0x{event.file_offset:08X}",
                f"{event.time_seconds * 1000:.6f}",
                f"{event.delta_seconds * 1_000_000:.3f}",
                event.timestamp_raw,
                event.event_id,
                event.event_name,
                event.context_id,
                f"0x{event.flags:02X}",
                "TAK" if event.is_isr else "nie",
                event.value,
            ), tags=(tag,) if tag else ())
        status.set(
            f"Widoczne: {len(filtered_events)} / {stats.frames} | bajty: {stats.bytes_total} | "
            f"odrzucone: {stats.discarded_bytes} | końcówka: {stats.trailing_bytes} | "
            f"przepełnienia timestampu: {stats.timestamp_wraps} | nazwy z trace.h: {names_count} | "
            f"zegar: {clock_hz} Hz"
        )

    def export_visible() -> None:
        selected = filedialog.asksaveasfilename(
            title="Eksport widocznych rekordów",
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Wszystkie pliki", "*.*")],
            initialfile=capture_path.with_suffix(".csv").name,
        )
        if selected:
            try:
                write_csv(Path(selected), filtered_events, clock_hz)
                messagebox.showinfo("Trace Viewer", f"Zapisano {len(filtered_events)} rekordów.")
            except OSError as exc:
                messagebox.showerror("Błąd zapisu", str(exc))

    ttk.Button(toolbar, text="Zastosuj filtr", command=refresh).pack(side="left")
    ttk.Button(toolbar, text="Wyczyść filtr", command=lambda: (
        filter_event.set(""), filter_context.set(""), only_isr.set(False), refresh()
    )).pack(side="left", padx=6)
    ttk.Button(toolbar, text="Eksportuj widoczne CSV", command=export_visible).pack(side="right")

    details = ttk.LabelFrame(root, text="Pliki", padding=6)
    details.pack(fill="x", padx=8, pady=(6, 0))
    ttk.Label(details, text=f"trace.h: {header_path}").pack(anchor="w")
    ttk.Label(details, text=f"capture.bin: {capture_path}").pack(anchor="w")
    ttk.Label(root, textvariable=status, relief="sunken", anchor="w", padding=5).pack(fill="x", side="bottom")

    filter_event.trace_add("write", lambda *_: None)
    root.bind("<Return>", refresh)
    refresh()
    root.mainloop()


def show_live_gui(
    names: dict[int, str],
    clock_hz: int,
    header_path: Path,
    capture_path: Path,
    poll_interval: float,
    max_visible: int,
) -> None:
    try:
        import tkinter as tk
        from tkinter import filedialog, messagebox, ttk
    except ImportError as exc:
        raise RuntimeError("Brak tkinter. Doinstaluj tkinter.") from exc

    root = tk.Tk()
    root.title(f"Trace Viewer LIVE - RealTerm - {capture_path.name}")
    root.geometry("1450x820")
    root.minsize(900, 500)

    events: list[TraceEvent] = []
    parser = StreamParser(names, clock_hz)
    messages: queue.Queue[tuple[str, object]] = queue.Queue()
    stop_event = threading.Event()
    paused = tk.BooleanVar(value=False)
    autoscroll = tk.BooleanVar(value=True)
    filter_event = tk.StringVar()
    filter_context = tk.StringVar()
    only_isr = tk.BooleanVar(value=False)
    status = tk.StringVar(value="Uruchamianie śledzenia pliku...")

    toolbar = ttk.Frame(root, padding=8)
    toolbar.pack(fill="x")
    ttk.Label(toolbar, text="Event ID/nazwa:").pack(side="left")
    ttk.Entry(toolbar, textvariable=filter_event, width=20).pack(side="left", padx=(4, 12))
    ttk.Label(toolbar, text="Context ID:").pack(side="left")
    ttk.Entry(toolbar, textvariable=filter_context, width=10).pack(side="left", padx=(4, 12))
    ttk.Checkbutton(toolbar, text="Tylko ISR", variable=only_isr).pack(side="left", padx=(0, 8))

    columns = (
        "nr", "offset", "time_ms", "delta_us", "timestamp", "event_id",
        "event_name", "context", "flags", "isr", "value"
    )
    frame = ttk.Frame(root)
    frame.pack(fill="both", expand=True, padx=8)
    tree = ttk.Treeview(frame, columns=columns, show="headings")
    headings = {
        "nr": "Nr", "offset": "Offset", "time_ms": "Czas [ms]",
        "delta_us": "Delta [us]", "timestamp": "Timestamp",
        "event_id": "Event ID", "event_name": "Nazwa zdarzenia",
        "context": "Context", "flags": "Flags", "isr": "ISR", "value": "Value"
    }
    widths = {
        "nr": 65, "offset": 100, "time_ms": 130, "delta_us": 120,
        "timestamp": 120, "event_id": 80, "event_name": 230, "context": 80,
        "flags": 70, "isr": 55, "value": 120
    }
    for column in columns:
        tree.heading(column, text=headings[column])
        tree.column(column, width=widths[column],
                    anchor="w" if column == "event_name" else "center")

    y_scroll = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    x_scroll = ttk.Scrollbar(frame, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)
    tree.grid(row=0, column=0, sticky="nsew")
    y_scroll.grid(row=0, column=1, sticky="ns")
    x_scroll.grid(row=1, column=0, sticky="ew")
    frame.rowconfigure(0, weight=1)
    frame.columnconfigure(0, weight=1)
    tree.tag_configure("isr", background="#FFF2CC")
    tree.tag_configure("warning", background="#F4CCCC")

    def matches(event: TraceEvent) -> bool:
        query = filter_event.get().strip().lower()
        context_query = filter_context.get().strip()
        if query and query not in str(event.event_id) and query not in event.event_name.lower():
            return False
        if context_query:
            try:
                if event.context_id != int(context_query, 0):
                    return False
            except ValueError:
                return False
        return not only_isr.get() or event.is_isr

    def insert_event(event: TraceEvent) -> None:
        if not matches(event):
            return
        tag = "warning" if event.unknown_flags else ("isr" if event.is_isr else "")
        tree.insert("", "end", values=(
            event.number, f"0x{event.file_offset:08X}",
            f"{event.time_seconds * 1000:.6f}",
            f"{event.delta_seconds * 1_000_000:.3f}",
            event.timestamp_raw, event.event_id, event.event_name, event.context_id,
            f"0x{event.flags:02X}", "TAK" if event.is_isr else "nie", event.value,
        ), tags=(tag,) if tag else ())

    def trim_visible_rows() -> None:
        children = tree.get_children()
        excess = len(children) - max_visible
        if excess > 0:
            tree.delete(*children[:excess])

    def update_status(prefix: str = "LIVE") -> None:
        stats = parser.stats()
        status.set(
            f"{prefix} | ramki: {stats.frames} | bajty: {stats.bytes_total} | "
            f"odrzucone: {stats.discarded_bytes} | bufor końcówki: {stats.trailing_bytes} | "
            f"wrap: {stats.timestamp_wraps} | widoczne: {len(tree.get_children())}"
        )

    def refresh_filters(*_args: object) -> None:
        tree.delete(*tree.get_children())
        for event in events[-max_visible:]:
            insert_event(event)
        update_status("LIVE / filtr")

    def clear_view() -> None:
        tree.delete(*tree.get_children())
        update_status("LIVE / wyczyszczono widok")

    def export_events() -> None:
        selected = filedialog.asksaveasfilename(
            title="Eksport zdarzeń LIVE", defaultextension=".csv",
            filetypes=[("CSV", "*.csv"), ("Wszystkie pliki", "*.*")],
            initialfile=capture_path.with_suffix(".csv").name,
        )
        if selected:
            try:
                visible = [event for event in events if matches(event)]
                write_csv(Path(selected), visible, clock_hz)
                messagebox.showinfo("Trace Viewer", f"Zapisano {len(visible)} rekordów.")
            except OSError as exc:
                messagebox.showerror("Błąd zapisu", str(exc))

    ttk.Button(toolbar, text="Zastosuj filtr", command=refresh_filters).pack(side="left")
    ttk.Button(toolbar, text="Wyczyść filtr", command=lambda: (
        filter_event.set(""), filter_context.set(""), only_isr.set(False), refresh_filters()
    )).pack(side="left", padx=6)
    ttk.Checkbutton(toolbar, text="Pauza widoku", variable=paused).pack(side="left", padx=(8, 2))
    ttk.Checkbutton(toolbar, text="Auto-scroll", variable=autoscroll).pack(side="left", padx=6)
    ttk.Button(toolbar, text="Wyczyść widok", command=clear_view).pack(side="left", padx=4)
    ttk.Button(toolbar, text="Eksportuj CSV", command=export_events).pack(side="right")

    details = ttk.LabelFrame(root, text="Tryb RealTerm LIVE", padding=6)
    details.pack(fill="x", padx=8, pady=(6, 0))
    ttk.Label(details, text=f"trace.h: {header_path}").pack(anchor="w")
    ttk.Label(details, text=f"obserwowany plik: {capture_path}").pack(anchor="w")
    ttk.Label(root, textvariable=status, relief="sunken", anchor="w", padding=5).pack(
        fill="x", side="bottom"
    )

    def process_messages() -> None:
        added = 0
        while added < 1000:
            try:
                message_type, payload = messages.get_nowait()
            except queue.Empty:
                break

            if message_type == "data":
                new_events = parser.feed(payload if isinstance(payload, bytes) else b"")
                events.extend(new_events)
                if not paused.get():
                    for event in new_events:
                        insert_event(event)
                    trim_visible_rows()
                    if new_events and autoscroll.get():
                        last = tree.get_children()
                        if last:
                            tree.see(last[-1])
                added += len(new_events)
            elif message_type == "status":
                status.set(str(payload))
            elif message_type == "reset":
                messagebox.showwarning("RealTerm", str(payload) + " Parser rozpoczyna nową sesję.")
            elif message_type == "error":
                messagebox.showerror("Trace Viewer", str(payload))

        update_status("LIVE / PAUZA" if paused.get() else "LIVE")
        root.after(50, process_messages)

    def close_application() -> None:
        stop_event.set()
        root.destroy()

    worker = threading.Thread(
        target=follow_capture_file,
        args=(capture_path, messages, stop_event, poll_interval),
        daemon=True,
        name="RealTermCaptureFollower",
    )
    worker.start()
    root.protocol("WM_DELETE_WINDOW", close_application)
    root.bind("<Return>", refresh_filters)
    root.after(50, process_messages)
    root.mainloop()


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Parser i przeglądarka ramek STM32 TraceEvent: AA 55 + <I H B B I"
    )
    parser.add_argument("trace_header", type=Path, help="Plik trace.h z identyfikatorami TRACE_*")
    parser.add_argument("capture", type=Path, help="Binarny plik capture.bin")
    parser.add_argument(
        "--clock", type=parse_clock, default=DEFAULT_CLOCK_HZ,
        help="Zegar CPU w Hz, np. 216000000U lub 216MHz (domyślnie: 216000000U)"
    )
    parser.add_argument("--csv", type=Path, help="Zapisz wszystkie rekordy do CSV")
    parser.add_argument("--no-gui", action="store_true", help="Nie otwieraj okna")
    parser.add_argument(
        "--follow", action="store_true",
        help="Śledź rosnący plik binarny zapisywany przez RealTerm"
    )
    parser.add_argument(
        "--poll-ms", type=int, default=50,
        help="Interwał sprawdzania pliku w ms (domyślnie: 50)"
    )
    parser.add_argument(
        "--max-visible", type=int, default=20000,
        help="Maksymalna liczba wierszy w GUI LIVE (domyślnie: 20000)"
    )
    return parser


def main() -> int:
    args = build_argument_parser().parse_args()

    if not args.trace_header.is_file():
        print(f"BŁĄD: nie znaleziono trace.h: {args.trace_header}", file=sys.stderr)
        return 2
    if args.poll_ms <= 0:
        print("BŁĄD: --poll-ms musi być większe od zera", file=sys.stderr)
        return 2
    if args.max_visible <= 0:
        print("BŁĄD: --max-visible musi być większe od zera", file=sys.stderr)
        return 2
    if RECORD_SIZE != 12 or FRAME_SIZE != 14:
        print("BŁĄD: niespodziewany rozmiar formatu rekordu", file=sys.stderr)
        return 3

    try:
        names = parse_trace_header(args.trace_header)
    except OSError as exc:
        print(f"BŁĄD odczytu trace.h: {exc}", file=sys.stderr)
        return 4

    if args.follow:
        if args.no_gui:
            print("BŁĄD: tryb --follow wymaga GUI; usuń --no-gui", file=sys.stderr)
            return 2
        print(f"Tryb: RealTerm LIVE, plik: {args.capture}")
        print(f"Zegar: {args.clock} Hz | Nazwy TRACE_*: {len(names)}")
        try:
            show_live_gui(
                names, args.clock, args.trace_header, args.capture,
                args.poll_ms / 1000.0, args.max_visible
            )
        except RuntimeError as exc:
            print(f"BŁĄD GUI: {exc}", file=sys.stderr)
            return 6
        return 0

    if not args.capture.is_file():
        print(f"BŁĄD: nie znaleziono capture.bin: {args.capture}", file=sys.stderr)
        return 2

    try:
        data = args.capture.read_bytes()
        events, stats = parse_capture(data, names, args.clock)
    except OSError as exc:
        print(f"BŁĄD odczytu: {exc}", file=sys.stderr)
        return 4

    print(f"Plik: {args.capture}")
    print(f"Zegar: {args.clock} Hz")
    print(f"Nazwy TRACE_*: {len(names)}")
    print(f"Ramki: {stats.frames}")
    print(f"Odrzucone bajty: {stats.discarded_bytes}")
    print(f"Niepełna końcówka: {stats.trailing_bytes}")
    print(f"Przepełnienia timestampu: {stats.timestamp_wraps}")

    if args.csv:
        write_csv(args.csv, events, args.clock)
        print(f"CSV: {args.csv}")
    if args.no_gui:
        return 0
    if not events:
        print("BŁĄD: nie znaleziono żadnej kompletnej ramki AA 55 + 12 bajtów", file=sys.stderr)
        return 5
    try:
        show_file_gui(
            events, stats, len(names), args.clock, args.trace_header, args.capture
        )
    except RuntimeError as exc:
        print(f"BŁĄD GUI: {exc}", file=sys.stderr)
        return 6
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
