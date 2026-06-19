from __future__ import annotations

import os

from flagar_alteracao_dashboard import run_flagar_alteracao_produtos_dashboard
from sheets_prices import load_env_file


def main() -> None:
    load_env_file()
    os.environ["HEADLESS"] = "true"
    result = run_flagar_alteracao_produtos_dashboard(
        locais=["BREWTECO TIJUCA"],
        skus="74737372828673",
        log=print,
    )
    print("RESULTADO_FINAL")
    print(result)


if __name__ == "__main__":
    main()
