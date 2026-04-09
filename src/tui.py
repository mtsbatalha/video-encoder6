"""Rich-based TUI components for the video encoder."""

import os
from pathlib import Path

from rich.console import Console
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
    console.print("  [3] Configurações")
    console.print("  [4] Gerenciar fila")
    console.print("  [5] Sair\n")

    choice = Prompt.ask(
        "Escolha uma opção",
        choices=["1", "2", "3", "4", "5"],
        default="1",
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
    """Display batch conversion preview."""
    table = Table(show_header=True, header_style="bold cyan", border_style="dim")
    table.add_column("#", style="yellow", width=4)
    table.add_column("Arquivo", style="white")
    table.add_column("Destino", style="dim")

    for i, f in enumerate(files, 1):
        dest = Path(f).stem + f"_{profile_suffix(profile)}.mkv"
        table.add_row(str(i), Path(f).name, dest)

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
    console.print("  [2] Automático — Detectar HDR/SDR e mostrar perfis compatíveis\n")

    choice = Prompt.ask(
        "Escolha o modo",
        choices=["1", "2"],
        default="2",
        console=console,
    )
    return "auto" if choice == "2" else "manual"


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

