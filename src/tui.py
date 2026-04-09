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
from rich.prompt import Prompt
from rich.table import Table

from src.profiles import ConversionProfile

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
    console.print("  [4] Sair\n")

    choice = Prompt.ask(
        "Escolha uma opção",
        choices=["1", "2", "3", "4"],
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
        TextColumn("[cyan]{task.fields[speed]}"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
        expand=True,
    )


def add_conversion_task(
    progress: Progress, filename: str, total: int = 100
) -> TaskID:
    """Add a conversion task to the progress tracker."""
    return progress.add_task(
        f"[white]{filename}",
        total=total,
        speed="",
    )


def update_progress(
    progress: Progress, task_id: TaskID, completed: int, speed: str = ""
) -> None:
    """Update a conversion task's progress."""
    progress.update(task_id, completed=completed, speed=speed)


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
