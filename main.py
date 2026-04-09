"""Video Encoder Manager - FFmpeg + CUDA conversion tool."""

import asyncio
import json
import os
from pathlib import Path

from rich.prompt import Confirm, Prompt

from src.encoder import ConversionResult, run_batch_conversions, run_conversion
from src.file_scanner import (
    build_output_path,
    scan_video_files,
)
from src.profiles import list_profiles
from src.tui import (
    add_conversion_task,
    console,
    create_progress,
    print_batch_preview,
    print_file_info,
    print_results,
    profile_suffix,
    select_profile_menu,
    show_banner,
    show_main_menu,
    update_progress,
)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def load_config() -> dict:
    """Load or create default configuration."""
    defaults = {
        "output_dir": os.path.join(os.getcwd(), "conversions"),
        "max_parallel": 2,
        "ffmpeg_path": "ffmpeg",
    }
    if os.path.exists(CONFIG_FILE):
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # Merge with defaults for any missing keys
        for key, val in defaults.items():
            config.setdefault(key, val)
        return config
    save_config(defaults)
    return defaults


def save_config(config: dict) -> None:
    """Save configuration to file."""
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)


async def convert_single_file(config: dict) -> None:
    """Handle single file conversion workflow."""
    profiles = list_profiles()

    # Get input file path
    console.print("[bold]Conversão de Arquivo Único[/bold]\n")
    input_path = Prompt.ask(
        "Caminho do arquivo de vídeo",
        console=console,
    ).strip()

    # Validate input file
    if not input_path or not os.path.isfile(input_path):
        console.print("[red]Arquivo não encontrado.[/red]")
        return

    # Select profile
    profile = select_profile_menu(profiles)
    if not profile:
        return

    # Build output path
    output_path = build_output_path(input_path, config["output_dir"], profile.suffix)

    # Show info and confirm
    print_file_info(input_path, profile, output_path)
    if not Confirm.ask("Iniciar conversão?", default=False, console=console):
        console.print("[yellow]Cancelado.[/yellow]")
        return

    # Build FFmpeg command
    cmd = profile.build_command(input_path, output_path)

    # Run conversion with progress
    with create_progress() as progress:
        task_id = add_conversion_task(progress, Path(input_path).name)

        def _cb(pct: int, speed: str) -> None:
            update_progress(progress, task_id, pct, speed)

        result = await run_conversion(input_path, output_path, cmd, progress_callback=_cb)

    print_results([{"file": result.file, "success": result.success, "details": result.details}])


async def convert_batch(config: dict) -> None:
    """Handle batch folder conversion workflow."""
    profiles = list_profiles()

    console.print("[bold]Conversão em Lote[/bold]\n")
    folder_path = Prompt.ask(
        "Caminho da pasta com os vídeos",
        console=console,
    ).strip()

    if not folder_path or not os.path.isdir(folder_path):
        console.print("[red]Pasta não encontrada.[/red]")
        return

    # Scan for video files
    files = scan_video_files(folder_path)
    if not files:
        console.print("[yellow]Nenhum arquivo de vídeo encontrado na pasta.[/yellow]")
        return

    console.print(f"[green]{len(files)}[/green] arquivo(s) encontrado(s).")

    # Select profile
    profile = select_profile_menu(profiles)
    if not profile:
        return

    # Show preview
    print_batch_preview(files, profile, config["output_dir"])

    # Confirm
    if not Confirm.ask(
        f"Iniciar conversão de {len(files)} arquivo(s)?", default=False, console=console
    ):
        console.print("[yellow]Cancelado.[/yellow]")
        return

    # Build jobs
    jobs = []
    for f in files:
        output_path = build_output_path(f, config["output_dir"], profile.suffix)
        cmd = profile.build_command(f, output_path)
        jobs.append({
            "input_path": f,
            "output_path": output_path,
            "cmd": cmd,
        })

    # Run batch conversion with progress
    max_parallel = config["max_parallel"]
    console.print(f"[dim]Parallelismo: {max_parallel} conversão(ões) simultâneas[/dim]\n")

    with create_progress() as progress:
        # Create all tasks as "queued" (spinner not shown yet)
        task_ids = {}
        for f in files:
            task_ids[f] = add_conversion_task(progress, Path(f).name, start=False)

        def _cb(filename: str, pct: int, speed: str, just_started: bool = False) -> None:
            if filename in task_ids and just_started:
                progress.start_task(task_ids[filename])
            if filename in task_ids:
                update_progress(progress, task_ids[filename], pct, speed)

        results: list[ConversionResult] = await run_batch_conversions(
            jobs,
            max_parallel=max_parallel,
            progress_callback=_cb,
        )

    # Print results
    result_dicts = [
        {"file": r.file, "success": r.success, "details": r.details}
        for r in results
    ]
    print_results(result_dicts)


async def settings_menu(config: dict) -> None:
    """Handle settings workflow."""
    console.print("[bold]Configurações[/bold]\n")

    console.print(f"  Pasta de saída: [cyan]{config['output_dir']}[/cyan]")
    console.print(f"  Conversões paralelas: [cyan]{config['max_parallel']}[/cyan]")
    console.print(f"  FFmpeg: [cyan]{config['ffmpeg_path']}[/cyan]\n")

    # Output directory
    new_dir = Prompt.ask(
        "Nova pasta de saída (Enter para manter)",
        default="",
        console=console,
    ).strip()
    if new_dir:
        config["output_dir"] = os.path.abspath(new_dir)

    # Parallel count
    new_parallel = Prompt.ask(
        "Número de conversões paralelas (1-8, Enter para manter)",
        default=str(config["max_parallel"]),
        console=console,
    ).strip()
    if new_parallel:
        try:
            val = int(new_parallel)
            if 1 <= val <= 8:
                config["max_parallel"] = val
            else:
                console.print("[yellow]Valor fora do intervalo (1-8), mantendo atual.[/yellow]")
        except ValueError:
            console.print("[yellow]Valor inválido, mantendo atual.[/yellow]")

    save_config(config)
    console.print("\n[green]Configurações salvas.[/green]")


async def main() -> None:
    """Main entry point."""
    config = load_config()

    # Ensure output directory exists
    os.makedirs(config["output_dir"], exist_ok=True)

    while True:
        show_banner()
        choice = show_main_menu()

        if choice == "1":
            await convert_single_file(config)
        elif choice == "2":
            await convert_batch(config)
        elif choice == "3":
            await settings_menu(config)
        elif choice == "4":
            console.print("[dim]Até mais![/dim]\n")
            break

        input("\nPressione Enter para continuar...")


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
