"""Video Encoder Manager - FFmpeg + CUDA conversion tool."""

import asyncio
import json
import os
import time
from pathlib import Path

from rich.prompt import Confirm, Prompt
from rich.panel import Panel

from src.encoder import run_conversion
from src.file_scanner import (
    build_output_path,
    scan_video_files,
)
from src.profiles import list_profiles
from src.queue_manager import QueueManager
from src.tui import (
    add_conversion_task,
    console,
    create_progress,
    print_batch_preview,
    print_file_info,
    select_profile_menu,
    show_banner,
    show_main_menu,
    show_queue_table,
    show_queue_menu,
    prompt_job_id,
    update_progress,
    prompt_source_type,
    prompt_remote_path,
)
from src.remote import (
    create_temp_dir,
    cleanup_temp_dir,
    copy_remote_source,
)

CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config.json")


def resolve_output_path(output_path: str, policy: str) -> str | None:
    """Resolve output path based on file-exists policy.

    Returns the path to use, or None if the file should be skipped.
    """
    if not os.path.exists(output_path):
        return output_path

    if policy == "skip":
        return None

    if policy == "copy":
        directory = os.path.dirname(output_path)
        base = Path(output_path).stem
        ext = Path(output_path).suffix
        counter = 1
        while True:
            new_path = os.path.join(directory, f"{base}_{counter}{ext}")
            if not os.path.exists(new_path):
                return new_path
            counter += 1

    # "overwrite" — use original path, FFmpeg -y will overwrite
    return output_path


def load_config() -> dict:
    """Load or create default configuration."""
    defaults = {
        "output_dir": os.path.join(os.getcwd(), "conversions"),
        "max_parallel": 2,
        "ffmpeg_path": "ffmpeg",
        "on_file_exists": "skip",  # skip, overwrite, copy
        "cleanup_remote_files": "always",  # always, never, ask
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


async def convert_single_file(config: dict, queue: QueueManager) -> None:
    """Handle single file conversion workflow — adds to queue."""
    profiles = list_profiles()

    console.print("[bold]Conversão de Arquivo Único[/bold]\n")

    # Ask if source is local or remote
    source_type = prompt_source_type()
    remote_temp_dir = None

    if source_type == "remote":
        remote_path = prompt_remote_path()
        if not remote_path:
            return

        temp_dir = create_temp_dir()
        console.print(f"\n[dim]Copiando para: {temp_dir}[/dim]\n")

        def _copy_progress(line: str):
            console.print(f"  [dim]{line}[/dim]")

        success, method = copy_remote_source(remote_path, temp_dir, _copy_progress)

        if not success:
            console.print("[red]Falha ao copiar arquivos. Verifique se rclone ou rsync está disponível.[/red]")
            cleanup_temp_dir(temp_dir)
            return

        console.print(f"\n[green]Cópia concluída ({method}).[/green]\n")

        # Scan to find video files in temp dir
        files = scan_video_files(temp_dir)
        if not files:
            console.print("[yellow]Nenhum arquivo de vídeo encontrado no caminho remoto.[/yellow]")
            cleanup_temp_dir(temp_dir)
            return

        # For single file: use first found video
        input_path = files[0]
        remote_temp_dir = temp_dir
        console.print(f"[green]Arquivo encontrado: {Path(input_path).name}[/green]\n")
    else:
        input_path = Prompt.ask(
            "Caminho do arquivo de vídeo",
            console=console,
        ).strip()

        if not input_path or not os.path.isfile(input_path):
            console.print("[red]Arquivo não encontrado.[/red]")
            return

    # Select profile
    profile = select_profile_menu(profiles)
    if not profile:
        return

    # Build output path
    output_path = build_output_path(input_path, config["output_dir"], profile.suffix)
    resolved = resolve_output_path(output_path, config["on_file_exists"])

    if resolved is None:
        console.print(f"[yellow]Arquivo já existe, pulando:[/yellow] [dim]{output_path}[/dim]")
        return

    # Show info and confirm
    print_file_info(input_path, profile, resolved)
    if not Confirm.ask("Adicionar à fila?", default=True, console=console):
        console.print("[yellow]Cancelado.[/yellow]")
        return

    # Add to queue
    job = queue.add(
        input_path=input_path,
        output_path=resolved,
        profile_id=profile.id,
        profile_name=profile.name,
        remote_temp_dir=remote_temp_dir,
    )
    console.print(f"\n[green]Job adicionado à fila![/green] [dim]ID: {job.id}[/dim]")
    console.print(f"[dim]Use 'Gerenciar Fila' para processar.[/dim]\n")


async def convert_batch(config: dict, queue: QueueManager) -> None:
    """Handle batch folder conversion workflow — adds to queue."""
    profiles = list_profiles()

    console.print("[bold]Conversão em Lote[/bold]\n")

    # Ask if source is local or remote
    source_type = prompt_source_type()
    remote_temp_dir = None

    if source_type == "remote":
        remote_path = prompt_remote_path()
        if not remote_path:
            return

        temp_dir = create_temp_dir()
        console.print(f"\n[dim]Copiando para: {temp_dir}[/dim]\n")

        def _copy_progress(line: str):
            console.print(f"  [dim]{line}[/dim]")

        success, method = copy_remote_source(remote_path, temp_dir, _copy_progress)

        if not success:
            console.print("[red]Falha ao copiar arquivos. Verifique se rclone ou rsync está disponível.[/red]")
            cleanup_temp_dir(temp_dir)
            return

        console.print(f"\n[green]Cópia concluída ({method}).[/green]\n")

        folder_path = temp_dir
        remote_temp_dir = temp_dir
    else:
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
        console.print("[yellow]Nenhum arquivo de vídeo encontrado.[/yellow]")
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
        f"Adicionar {len(files)} arquivo(s) à fila?", default=True, console=console
    ):
        console.print("[yellow]Cancelado.[/yellow]")
        return

    # Add to queue
    jobs_added = []
    skipped_count = 0
    for f in files:
        output_path = build_output_path(f, config["output_dir"], profile.suffix)
        resolved = resolve_output_path(output_path, config["on_file_exists"])

        if resolved is None:
            console.print(f"[yellow]Pulando (já existe):[/yellow] [dim]{Path(f).name}[/dim]")
            skipped_count += 1
            continue

        job = queue.add(
            input_path=f,
            output_path=resolved,
            profile_id=profile.id,
            profile_name=profile.name,
            remote_temp_dir=remote_temp_dir,
        )
        jobs_added.append(job)

    console.print(f"\n[green]{len(jobs_added)} job(s) adicionado(s) à fila![/green]")
    if skipped_count:
        console.print(f"[yellow]{skipped_count} arquivo(s) pulado(s) (já existem).[/yellow]")
    console.print(f"[dim]Use 'Gerenciar Fila' para processar.[/dim]\n")


def _handle_remote_cleanup(config: dict, queue: QueueManager) -> None:
    """Clean up remote temp dirs after queue processing based on config."""
    pending_dirs = queue.get_pending_remote_dirs()
    if not pending_dirs:
        return

    policy = config.get("cleanup_remote_files", "always")
    cleaned_ids = []

    for job_id, temp_dir in pending_dirs:
        if policy == "never":
            console.print(f"[dim]Arquivos temporários mantidos: {temp_dir}[/dim]")
            continue

        if policy == "ask":
            if not Confirm.ask(
                f"Deletar arquivos temporários de job {job_id}? ({temp_dir})",
                default=True,
                console=console,
            ):
                console.print(f"[dim]Mantendo: {temp_dir}[/dim]")
                continue

        if cleanup_temp_dir(temp_dir):
            cleaned_ids.append(job_id)
            console.print(f"[dim]Temp limpo: {temp_dir}[/dim]")
        else:
            console.print(f"[yellow]Falha ao limpar: {temp_dir}[/yellow]")
            cleaned_ids.append(job_id)

    if cleaned_ids:
        queue.mark_remote_dirs_cleaned(cleaned_ids)


async def process_queue(config: dict, queue: QueueManager) -> None:
    """Process the queue sequentially, respecting pause state."""
    if queue.paused:
        console.print("[yellow]Fila pausada. Retome antes de processar.[/yellow]")
        return

    if queue.pending_count == 0 and queue.scheduled_count == 0:
        console.print("[yellow]Nenhum job pendente ou agendado na fila.[/yellow]")
        return

    console.print(f"\n[bold]Processando fila...[/bold] [dim]({queue.pending_count} pendente(s))[/dim]\n")

    # Import profiles to build commands
    from src.profiles import get_profile

    with create_progress() as progress:
        while True:
            if queue.paused:
                console.print("\n[yellow]Fila pausada pelo usuário.[/yellow]")
                break

            job = queue.get_next_job()
            if job is None:
                break

            # Build command from profile
            profile = get_profile(job.profile_id)
            if profile is None:
                queue.mark_job_done(job.id, False, f"Perfil '{job.profile_id}' não encontrado")
                console.print(f"[red]Perfil '{job.profile_id}' não encontrado para job {job.id}[/red]")
                continue

            cmd = profile.build_command(job.input_path, job.output_path)

            # Create progress task
            task_id = add_conversion_task(progress, Path(job.input_path).name)

            # Throttled disk save: persist to disk every 5s
            _last_save = time.monotonic()
            def _cb(pct: int, speed: str) -> None:
                nonlocal _last_save
                update_progress(progress, task_id, pct, speed)
                queue.mark_job_progress(job.id, pct, speed)
                now = time.monotonic()
                if now - _last_save >= 5.0:
                    _last_save = now
                    queue.save()

            result = await run_conversion(
                job.input_path, job.output_path, cmd, progress_callback=_cb
            )

            # Final save
            queue.save()

            queue.mark_job_done(job.id, result.success, result.details if not result.success else None)

            status = "[green]OK[/green]" if result.success else f"[red]ERRO: {result.details}[/red]"
            console.print(f"[dim]  {Path(job.input_path).name} → {status}[/dim]")

    # Final summary
    stats = queue.get_stats()
    console.print(
        Panel(
            f"[green]{stats['completed']} concluído(s)[/green]  "
            f"[red]{stats['failed']} falha(s)[/red]  "
            f"[yellow]{stats['pending']} pendente(s)[/yellow]",
            title="[bold]Processamento da Fila[/bold]",
            border_style="green" if stats["failed"] == 0 else "yellow",
        )
    )
    console.print()

    # Cleanup remote temp dirs
    _handle_remote_cleanup(config, queue)


async def manage_queue_menu(config: dict, queue: QueueManager) -> None:
    """Interactive queue management submenu."""
    while True:
        show_queue_table(queue)
        choice = show_queue_menu(queue)

        if choice == "0":
            break
        elif choice == "1":
            await process_queue(config, queue)
        elif choice == "2":
            new_state = queue.toggle_pause()
            state = "pausada" if new_state else "retomada"
            console.print(f"[green]Fila {state}.[/green]\n")
        elif choice == "3":
            job_id = prompt_job_id(queue, "mover para cima")
            if job_id and queue.move_up(job_id):
                console.print("[green]Job movido para cima.[/green]\n")
        elif choice == "4":
            job_id = prompt_job_id(queue, "mover para baixo")
            if job_id and queue.move_down(job_id):
                console.print("[green]Job movido para baixo.[/green]\n")
        elif choice == "5":
            job_id = prompt_job_id(queue, "remover")
            if job_id and queue.remove(job_id):
                console.print("[green]Job removido.[/green]\n")
        elif choice == "6":
            removed = queue.remove_completed()
            console.print(f"[green]{removed} job(s) concluído(s) removido(s).[/green]\n")
        elif choice == "7":
            retried = queue.retry_failed()
            console.print(f"[green]{retried} job(s) com falha reenviado(s) para pendente.[/green]\n")
        elif choice == "8":
            job_id = prompt_job_id(queue, "agendar")
            if job_id:
                scheduled_at = Prompt.ask(
                    "Data/hora (YYYY-MM-DDTHH:MM:SS, ex: 2026-04-09T02:00:00)",
                    console=console,
                ).strip()
                for j in queue.jobs:
                    if j.id == job_id:
                        j.scheduled_at = scheduled_at
                        j.status = "scheduled"
                        queue.save()
                        console.print(f"[green]Job agendado para {scheduled_at}.[/green]\n")
                        break
        elif choice == "9":
            if Confirm.ask("Limpar toda a fila?", default=False, console=console):
                queue.clear_all()
                console.print("[green]Fila limpa.[/green]\n")


async def settings_menu(config: dict) -> None:
    """Handle settings workflow."""
    console.print("[bold]Configurações[/bold]\n")

    console.print(f"  Pasta de saída: [cyan]{config['output_dir']}[/cyan]")
    console.print(f"  Conversões paralelas: [cyan]{config['max_parallel']}[/cyan]")
    console.print(f"  FFmpeg: [cyan]{config['ffmpeg_path']}[/cyan]")

    labels = {"skip": "Pular existentes", "overwrite": "Sobrescrever", "copy": "Criar cópia"}
    console.print(f"  Arquivos existentes: [cyan]{labels.get(config['on_file_exists'], config['on_file_exists'])}[/cyan]")

    cleanup_labels = {"always": "Deletar após conversão", "never": "Manter", "ask": "Perguntar"}
    console.print(f"  Arquivos remotos: [cyan]{cleanup_labels.get(config['cleanup_remote_files'], config['cleanup_remote_files'])}[/cyan]\n")

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

    # On file exists policy
    console.print("\n[yellow]Quando arquivo de destino já existe:[/yellow]")
    console.print("  [dim]1[/dim] - Pular (não converte)")
    console.print("  [dim]2[/dim] - Sobrescrever")
    console.print("  [dim]3[/dim] - Criar cópia (nome_1, nome_2, ...)")
    policy_map = {"1": "skip", "2": "overwrite", "3": "copy"}
    inverse_map = {"skip": "1", "overwrite": "2", "copy": "3"}
    choice = Prompt.ask(
        "Escolha (1-3, Enter para manter)",
        default=inverse_map.get(config["on_file_exists"], "1"),
        console=console,
    ).strip()
    if choice in policy_map:
        config["on_file_exists"] = policy_map[choice]

    # Cleanup remote files policy
    console.print("\n[yellow]Arquivos remotos após conversão:[/yellow]")
    console.print("  [dim]1[/dim] - Deletar automaticamente (padrão)")
    console.print("  [dim]2[/dim] - Manter arquivos temporários")
    console.print("  [dim]3[/dim] - Perguntar antes de deletar")
    cleanup_map = {"1": "always", "2": "never", "3": "ask"}
    inverse_cleanup = {"always": "1", "never": "2", "ask": "3"}
    cleanup_choice = Prompt.ask(
        "Escolha (1-3, Enter para manter)",
        default=inverse_cleanup.get(config["cleanup_remote_files"], "1"),
        console=console,
    ).strip()
    if cleanup_choice in cleanup_map:
        config["cleanup_remote_files"] = cleanup_map[cleanup_choice]

    save_config(config)
    console.print("\n[green]Configurações salvas.[/green]")


async def main() -> None:
    """Main entry point."""
    config = load_config()
    queue = QueueManager()

    # Ensure output directory exists
    os.makedirs(config["output_dir"], exist_ok=True)

    while True:
        show_banner()
        choice = show_main_menu()

        if choice == "1":
            await convert_single_file(config, queue)
        elif choice == "2":
            await convert_batch(config, queue)
        elif choice == "3":
            await settings_menu(config)
        elif choice == "4":
            await manage_queue_menu(config, queue)
        elif choice == "5":
            console.print("[dim]Até mais![/dim]\n")
            break

        input("\nPressione Enter para continuar...")


if __name__ == "__main__":
    asyncio.run(main())
