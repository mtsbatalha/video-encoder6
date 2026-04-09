"""Rich-based TUI components for the video encoder."""

import os
import sys
import threading
import time
from pathlib import Path

from rich.console import Console
from rich.live import Live
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from src.profiles import ConversionProfile
from src.queue_manager import QueueManager, QueueJob

console = Console()


def _check_keyboard_input() -> str | None:
    """Non-blocking single-character keyboard input (Windows only).

    Returns the pressed character or None if no key was pressed.
    """
    if sys.platform == "win32":
        try:
            import msvcrt
            if msvcrt.kbhit():
                ch = msvcrt.getwch()
                # Extended key codes (arrows, F-keys, etc.) — skip
                if ch in ("\xe0", "\x00"):
                    msvcrt.getwch()  # consume the second byte
                    return None
                # Ignore Enter / newline
                if ch in ("\r", "\n"):
                    return None
                return ch
        except (ImportError, OSError):
            pass
    return None


def _msvcrt_getwch_input(timeout: float = 0.5) -> str | None:
    """Fallback input detection using a thread that blocks on msvcrt.getwch().

    This works even when msvcrt.kbhit() fails inside Rich Live (Windows).
    Returns the pressed character or None if timeout expires.
    """
    if sys.platform != "win32":
        return None
    try:
        import msvcrt
        result: list[str] = []

        def _wait_key():
            ch = msvcrt.getwch()
            # Extended key codes — skip
            if ch in ("\xe0", "\x00"):
                msvcrt.getwch()
                return
            if ch in ("\r", "\n"):
                return
            result.append(ch)

        t = threading.Thread(target=_wait_key, daemon=True)
        t.start()
        t.join(timeout=timeout)
        return result[0] if result else None
    except (ImportError, OSError):
        return None


def show_banner() -> None:
    """Display the application banner."""
    console.print()
    console.print(
        Panel.fit(
            "[bold cyan]Video Encoder[/bold cyan] - Conversor de Vídeo FFmpeg + CUDA\n"
            "[dim]v1.0.0 -- HEVC NVENC | HDR/SDR | Batch Conversion[/dim]",
            border_style="cyan",
        )
    )
    console.print()


def show_main_menu() -> str:
    """Show the main menu and return the user's choice."""
    console.print("[bold]Menu Principal:[/bold]\n")
    console.print("  [1] Converter arquivo único")
    console.print("  [2] Conversão em lote (pasta)")
    console.print("  [3] Gerenciar fila")
    console.print("  [4] Configurações")
    console.print("  [5] Outros")
    console.print("  [6] Sair\n")

    choice = Prompt.ask(
        "Escolha uma opção",
        choices=["1", "2", "3", "4", "5", "6"],
        default="1",
        console=console,
    )
    return choice


def show_others_menu() -> str:
    """Show the 'Outros' submenu and return the user's choice."""
    console.print("[bold]Outros:[/bold]\n")
    console.print("  [1] Encerrar processos FFmpeg")
    console.print("  [0] Voltar\n")

    choice = Prompt.ask(
        "Escolha uma opção",
        choices=["0", "1"],
        default="0",
        console=console,
    )
    return choice


def select_profile_menu(profiles: list[ConversionProfile]) -> ConversionProfile | None:
    """Show profile selection menu and return the chosen profile."""
    console.print("\n[bold]Perfis de Conversão:[/bold]\n")

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", style="yellow", width=4)
    table.add_column("Perfil", style="bold white")
    table.add_column("Descrição", style="dim")

    for i, profile in enumerate(profiles, 1):
        table.add_row(str(i), profile.name, profile.description)

    console.print(table)
    console.print()

    choices = [str(i) for i in range(1, len(profiles) + 1)]
    choice = Prompt.ask(
        "Selecione o perfil",
        choices=choices,
        default="1",
        console=console,
    )
    return profiles[int(choice) - 1]


def print_file_info(input_path: str, profile: ConversionProfile, output_path: str) -> None:
    """Display file conversion info before starting."""
    file_size = _format_size(os.path.getsize(input_path))
    filename = Path(input_path).name

    console.print(
        Panel(
            f"[bold]Arquivo:[/bold]  {filename}\n"
            f"[bold]Tamanho:[/bold]  {file_size}\n"
            f"[bold]Perfil:[/bold]   {profile.name}\n"
            f"[bold]Saída:[/bold]    {output_path}",
            title="[cyan]Resumo da Conversão[/cyan]",
            border_style="cyan",
        )
    )
    console.print()


def print_batch_preview(
    files: list[str], profile: ConversionProfile, output_dir: str
) -> None:
    """Display batch conversion preview (single profile)."""
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", style="yellow", width=4)
    table.add_column("Arquivo", style="white")
    table.add_column("Perfil", style="cyan", width=16)
    table.add_column("Destino", style="dim")

    for i, f in enumerate(files, 1):
        dest = Path(f).stem + f"_{profile_suffix(profile)}.mkv"
        table.add_row(str(i), Path(f).name, profile.name, dest)

    console.print(
        Panel(
            f"[bold]{len(files)}[/bold] arquivo(s) encontrado(s)\n"
            f"[bold]Perfil:[/bold] {profile.name}",
            title="[cyan]Conversão em Lote[/cyan]",
            border_style="cyan",
        )
    )
    console.print(table)
    console.print()


def print_auto_batch_preview(
    file_profiles: list[tuple[str, ConversionProfile]], output_dir: str,
    hdr_count: int, sdr_count: int,
) -> None:
    """Display batch conversion preview when files have mixed profiles."""
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", style="yellow", width=4)
    table.add_column("Arquivo", style="white")
    table.add_column("Perfil", style="cyan", width=16)
    table.add_column("Destino", style="dim")

    for i, (f, profile) in enumerate(file_profiles, 1):
        dest = Path(f).stem + f"_{profile_suffix(profile)}.mkv"
        table.add_row(str(i), Path(f).name, profile.name, dest)

    summary_parts = [f"[bold]{len(file_profiles)}[/bold] arquivo(s)"]
    if hdr_count:
        summary_parts.append(f"[magenta]{hdr_count} HDR[/magenta]")
    if sdr_count:
        summary_parts.append(f"[cyan]{sdr_count} SDR[/cyan]")

    console.print(
        Panel(
            "  ".join(summary_parts),
            title="[cyan]Conversão em Lote[/cyan]",
            border_style="cyan",
        )
    )
    console.print(table)
    console.print()


def profile_suffix(profile: ConversionProfile) -> str:
    """Return the profile's suffix for output naming."""
    return profile.suffix


def create_progress() -> Progress:
    """Create a Rich Progress object for conversions."""
    return Progress(
        SpinnerColumn(),
        TextColumn("[bold blue]{task.description}"),
        BarColumn(bar_width=40),
        TextColumn("[bold]{task.percentage:>3.0f}%"),
        TextColumn("[dim]|[dim]"),
        TextColumn("[cyan]{task.fields[ff_speed]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
        refresh_per_second=4,
    )


def add_conversion_task(
    progress: Progress, filename: str, total: int = 100, start: bool = True
) -> TaskID:
    """Add a conversion task to the progress tracker."""
    return progress.add_task(
        f"[white]{filename}",
        total=total,
        ff_speed="",
        start=start,
    )


def update_progress(
    progress: Progress, task_id: TaskID, completed: int, speed: str = ""
) -> None:
    """Update a conversion task's progress.

    Updates 'completed' (letting Rich auto-calculate speed for ETA)
    and stores FFmpeg speed as a custom field 'ff_speed' for display.
    """
    progress.update(task_id, completed=completed, ff_speed=speed)


def print_results(results: list[dict]) -> None:
    """Display conversion results summary."""
    success = sum(1 for r in results if r["success"])
    failed = len(results) - success

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("Status", style="white", width=8)
    table.add_column("Arquivo", style="white")
    table.add_column("Detalhes", style="dim")

    for r in results:
        status = "[green]OK[/green]" if r["success"] else "[red]ERRO[/red]"
        details = r.get("details", "")
        table.add_row(status, Path(r["file"]).name, details)

    console.print()
    console.print(
        Panel(
            f"[green]{success} concluído(s)[/green]  "
            f"[red]{failed} falha(s)[/red]",
            title="[bold]Resultado[/bold]",
            border_style="green" if failed == 0 else "yellow",
        )
    )
    console.print(table)
    console.print()


def _format_size(size_bytes: int) -> str:
    """Format file size in human-readable format."""
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size_bytes < 1024:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024
    return f"{size_bytes:.1f} PB"


def show_queue_table(queue: QueueManager) -> None:
    """Display the current queue as a formatted table."""
    stats = queue.get_stats()
    paused = stats["paused"]
    status_tag = "[red]PAUSADA[/red]" if paused else "[green]ATIVA[/green]"

    console.print(
        Panel(
            f"Estado: {status_tag}  |  "
            f"Pendentes: [yellow]{stats['pending']}[/yellow]  "
            f"Rodando: [blue]{stats['running']}[/blue]  "
            f"Concluídas: [green]{stats['completed']}[/green]  "
            f"Falhas: [red]{stats['failed']}[/red]  "
            f"Agendadas: [cyan]{stats['scheduled']}[/cyan]",
            title="[bold]Fila de Conversão[/bold]",
            border_style="cyan",
        )
    )

    if not queue.jobs:
        console.print("[dim]  (fila vazia)[/dim]")
        console.print()
        return

    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", style="yellow", width=3)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Arquivo", style="white")
    table.add_column("Perfil", style="cyan", width=12)
    table.add_column("Progresso", style="white", width=10)
    table.add_column("Velocidade", style="dim", width=8)
    table.add_column("Status", style="white", width=12)

    pending_idx = 0
    for j in queue.jobs:
        pending_idx += 1
        # Status color
        status_map = {
            "pending": "[yellow]Pendente[/yellow]",
            "running": "[blue]Rodando[/blue]",
            "completed": "[green]Concluído[/green]",
            "failed": "[red]Falha[/red]",
            "paused": "[magenta]Pausado[/magenta]",
            "scheduled": "[cyan]Agendado[/cyan]",
        }
        status_text = status_map.get(j.status, j.status)

        # Progress bar visualization
        if j.status == "completed":
            progress_bar = "[green]██████████[/green]"
        elif j.status == "failed":
            progress_bar = "[red]██████████[/red]"
        elif j.progress_pct > 0:
            filled = j.progress_pct // 10
            empty = 10 - filled
            progress_bar = f"[yellow]{'█' * filled}{'░' * empty}[/yellow]"
        else:
            progress_bar = "[dim]░░░░░░░░░░[/dim]"

        progress_text = f"{j.progress_pct}%"
        speed_text = j.speed or ""
        filename = Path(j.input_path).name

        table.add_row(
            str(pending_idx),
            j.id,
            filename,
            j.profile_name[:12] if j.profile_name else "",
            progress_text,
            speed_text,
            status_text,
        )

    console.print(table)
    console.print()


def show_queue_menu(queue: QueueManager) -> str:
    """Show queue management menu and return choice."""
    console.print("[bold]Gerenciar Fila:[/bold]\n")
    console.print("  [1] Processar fila")
    console.print("  [2] Pausar / Retomar")
    console.print("  [3] Mover job para cima")
    console.print("  [4] Mover job para baixo")
    console.print("  [5] Remover job")
    console.print("  [6] Remover concluídos")
    console.print("  [7] Retentar falhas")
    console.print("  [8] Agendar job")
    console.print("  [9] Limpar fila")
    console.print("  [0] Voltar\n")

    choices = [str(i) for i in range(10)]
    return Prompt.ask(
        "Escolha uma opção",
        choices=choices,
        default="0",
        console=console,
    )


def _render_queue_panel(queue: QueueManager, has_bg_task: bool, paused_override: bool | None = None) -> Panel:
    """Render the queue table + menu as a single Panel for Live display."""
    stats = queue.get_stats()
    is_paused = paused_override if paused_override is not None else stats["paused"]
    status_tag = "[red]PAUSADA[/red]" if is_paused else "[green]ATIVA[/green]"

    lines = [
        f"Estado: {status_tag}  |  "
        f"Pendentes: [yellow]{stats['pending']}[/yellow]  "
        f"Rodando: [blue]{stats['running']}[/blue]  "
        f"Concluídas: [green]{stats['completed']}[/green]  "
        f"Falhas: [red]{stats['failed']}[/red]  "
        f"Agendadas: [cyan]{stats['scheduled']}[/cyan]",
    ]

    if has_bg_task:
        running_job = next((j for j in queue.jobs if j.status == "running"), None)
        if running_job:
            lines.append(
                f"[bold green]Convertendo: {Path(running_job.input_path).name} "
                f"({running_job.progress_pct}%)  |  {running_job.speed or ''}[/bold green]"
            )
        else:
            lines.append("[bold green]Processando fila em segundo plano...[/bold green]")

    table = Table(show_header=True, header_style="bold cyan", border_style="dim", padding=(0, 0))
    table.add_column("#", style="yellow", width=3)
    table.add_column("ID", style="dim", width=10)
    table.add_column("Arquivo", style="white")
    table.add_column("Perfil", style="cyan", width=12)
    table.add_column("Progresso", style="white", width=10)
    table.add_column("Velocidade", style="dim", width=10)
    table.add_column("Status", style="white", width=12)

    pending_idx = 0
    for j in queue.jobs:
        pending_idx += 1
        status_map = {
            "pending": "[yellow]Pendente[/yellow]",
            "running": "[blue]Rodando[/blue]",
            "completed": "[green]Concluído[/green]",
            "failed": "[red]Falha[/red]",
            "paused": "[magenta]Pausado[/magenta]",
            "scheduled": "[cyan]Agendado[/cyan]",
        }
        status_text = status_map.get(j.status, j.status)

        if j.status == "completed":
            progress_bar = "[green]██████████[/green] 100%"
        elif j.status == "failed":
            progress_bar = "[red]Falha[/red]"
        elif j.progress_pct > 0:
            filled = j.progress_pct // 10
            empty = 10 - filled
            progress_bar = f"[yellow]{'█' * filled}{'░' * empty}[/yellow] {j.progress_pct}%"
        else:
            progress_bar = "[dim]░░░░░░░░░░ 0%[/dim]"

        speed_text = j.speed or ""
        filename = Path(j.input_path).name

        table.add_row(
            str(pending_idx),
            j.id,
            filename,
            j.profile_name[:12] if j.profile_name else "",
            progress_bar,
            speed_text,
            status_text,
        )

    menu_lines = [
        "",
        "[bold]Comandos:[/bold]",
        "[1] Processar fila   [2] Pausar/Retomar   [3]↑  [4]↓  [5] Remover  [6] Limpar concluídos",
        "[7] Retentar falhas  [8] Agendar          [9] Limpar fila        [0] Voltar",
        "[dim]Pressione a tecla do comando...[/dim]",
    ]

    full_text = "\n".join(lines) + "\n"
    if queue.jobs:
        from rich import box
        # Build renderable: text + table + menu
        from rich.console import Group
        menu_text = "\n".join(menu_lines)
        return Panel(
            Group(
                Text.from_markup(full_text),
                table,
                Text.from_markup(menu_text),
            ),
            title="[bold]Fila de Conversão[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
        )
    else:
        full_text += "[dim]  (fila vazia)[/dim]\n"
        full_text += "\n".join(menu_lines)
        return Panel(
            Text.from_markup(full_text),
            title="[bold]Fila de Conversão[/bold]",
            border_style="cyan",
            box=box.ROUNDED,
        )


def interactive_queue_menu(
    queue: QueueManager,
    has_bg_task: bool,
    on_command: callable,
    paused_override: bool | None = None,
) -> bool:
    """Show queue management menu with real-time updates via rich.Live.

    Polls for keyboard input (non-blocking) while the Live display
    auto-refreshes the queue table.

    Returns True if the user chose to exit (0), False otherwise.
    """
    # Commands that need blocking prompts (job ID, confirmations)
    # must stop the Live display first so Rich Prompt/Confirm can use stdin.
    PROMPT_COMMANDS = set("34589")

    def _make_panel() -> Panel:
        return _render_queue_panel(queue, has_bg_task(), paused_override)

    with Live(_make_panel(), console=console, refresh_per_second=2, screen=False) as live:
        try:
            while True:
                time.sleep(0.1)
                live.update(_make_panel())

                ch = _check_keyboard_input()

                # Fallback: thread-based input if msvcrt.kbhit() doesn't
                # detect keypresses inside Rich Live (known Windows issue).
                if ch is None:
                    ch = _msvcrt_getwch_input(timeout=0.2)

                if ch is None:
                    continue

                # Process command
                if ch == "0":
                    return True
                elif ch in "123456789":
                    if ch in PROMPT_COMMANDS:
                        # Stop Live so Rich Prompt/Confirm can use stdin cleanly
                        live.stop()
                        try:
                            on_command(ch)
                        finally:
                            live.start()
                    else:
                        # Commands 1,2,6,7 — no prompts needed
                        on_command(ch)
                    live.update(_make_panel())
        except KeyboardInterrupt:
            return False


def prompt_job_id(queue: QueueManager, action: str) -> str | None:
    """Prompt for a valid job ID from the queue."""
    jobs = queue.jobs
    if not jobs:
        console.print("[yellow]Fila vazia.[/yellow]")
        return None

    valid = [j.id for j in jobs]
    job_id = Prompt.ask(
        f"ID do job para {action} ({', '.join(valid)})",
        console=console,
    ).strip()

    if job_id not in valid:
        console.print(f"[yellow]Job '{job_id}' não encontrado.[/yellow]")
        return None
    return job_id


def prompt_conversion_mode() -> str:
    """Ask user to choose between manual or automatic profile selection.

    Returns 'manual' or 'auto'.
    """
    console.print("\n[bold]Modo de seleção de perfil:[/bold]\n")
    console.print("  [1] Manual — Escolher o perfil manualmente")
    console.print("  [2] Automático — Detectar HDR/SDR de cada arquivo e delegar automaticamente\n")

    choice = Prompt.ask(
        "Escolha o modo",
        choices=["1", "2"],
        default="2",
        console=console,
    )
    return "auto" if choice == "2" else "manual"


def prompt_batch_auto_mode(hdr_count: int, sdr_count: int) -> tuple[str, str] | None:
    """Prompt for automatic batch mode settings.

    Shows HDR/SDR summary, asks for resolution and HDR output mode.

    Returns (resolution, hdr_mode) where:
      - resolution: "4k" or "1080p"
      - hdr_mode: "hdr" (keep HDR) or "sdr" (convert HDR to SDR)
        Only relevant when hdr_count > 0.
    """
    console.print(f"\n[bold]Resumo da detecção:[/bold]")
    if hdr_count:
        console.print(f"  [magenta]{hdr_count}[/magenta] arquivo(s) HDR")
    if sdr_count:
        console.print(f"  [cyan]{sdr_count}[/cyan] arquivo(s) SDR")
    console.print()

    # Resolution
    console.print("[bold]Resolução de saída:[/bold]\n")
    console.print("  [1] 4K")
    console.print("  [2] 1080p\n")

    res_choice = Prompt.ask(
        "Escolha a resolução",
        choices=["1", "2"],
        default="1",
        console=console,
    )
    resolution = "4k" if res_choice == "1" else "1080p"

    # HDR output mode (only if there are HDR files)
    hdr_mode = "sdr"  # default
    if hdr_count > 0:
        console.print(f"\n[bold]Arquivos HDR:[/bold]\n")
        console.print("  [1] Manter HDR (10-bit)")
        console.print("  [2] Converter para SDR (tonemap Hable)\n")

        hdr_choice = Prompt.ask(
            "Escolha o modo de saída para HDR",
            choices=["1", "2"],
            default="2",
            console=console,
        )
        hdr_mode = "hdr" if hdr_choice == "1" else "sdr"

    return resolution, hdr_mode


def prompt_source_type() -> str:
    """Ask if the source is local or remote. Returns 'local' or 'remote'."""
    console.print("\n[bold]Tipo de origem:[/bold]\n")
    console.print("  [1] Local (arquivo/pasta no computador)")
    console.print("  [2] Remoto (rclone mount, SMB, SSHFS, etc.)")

    choice = Prompt.ask(
        "Escolha o tipo de origem",
        choices=["1", "2"],
        default="1",
        console=console,
    )
    return "local" if choice == "1" else "remote"


def prompt_remote_path() -> str:
    """Prompt for a remote/mounted path (rclone remote, SSH mount, SMB, etc.)."""
    console.print("\n[bold]Caminho remoto[/bold]")
    console.print("[dim]Exemplos: gdrive:videos/, /mnt/smb/share/, user@host:/path[/dim]\n")

    path = Prompt.ask("Caminho remoto de origem", console=console).strip()
    if not path:
        console.print("[yellow]Nenhum caminho informado.[/yellow]")
    return path

