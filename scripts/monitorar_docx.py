from __future__ import annotations

from time import sleep

from gerar_site import INPUT_DIR, build_site


def snapshot() -> dict[str, int]:
    INPUT_DIR.mkdir(parents=True, exist_ok=True)
    return {
        item.name: item.stat().st_mtime_ns
        for item in INPUT_DIR.glob("*.docx")
        if item.is_file()
    }


def main() -> None:
    print("Monitor de DOCX iniciado.")
    print(f"Pasta observada: {INPUT_DIR}")
    print("Deixe esta janela aberta e jogue arquivos .docx na pasta de entrada.")

    previous = None
    while True:
        current = snapshot()
        if current != previous:
            try:
                articles = build_site()
                print(f"Site atualizado. Total de artigos: {len(articles)}")
            except Exception as exc:  # pragma: no cover
                print(f"Falha ao gerar o site: {exc}")
            previous = snapshot()
        sleep(3)


if __name__ == "__main__":
    main()
