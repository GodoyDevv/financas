import subprocess
import sys
from pathlib import Path


def test_requirements_txt_in_sync_with_uv_lock():
    """Garante que requirements.txt é idêntico à exportação do uv.lock (--no-dev --no-hashes)."""
    repo_root = Path(__file__).resolve().parent.parent
    req_file = repo_root / "requirements.txt"
    lock_file = repo_root / "uv.lock"

    assert req_file.exists(), "requirements.txt não encontrado na raiz do projeto"
    assert lock_file.exists(), "uv.lock não encontrado na raiz do projeto"

    # Executa uv export com os mesmos parâmetros do comando padrão
    cmd = [
        sys.executable,
        "-m",
        "uv",
        "export",
        "--no-dev",
        "--no-hashes",
    ]
    result = subprocess.run(cmd, cwd=repo_root, capture_output=True, text=True, check=True)

    # Ignora cabeçalhos de comentários gerados automaticamente para comparar os pacotes reais
    def extract_packages(text: str) -> list[str]:
        lines = []
        for line in text.replace("\r\n", "\n").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                lines.append(line)
        return lines

    exported_pkgs = extract_packages(result.stdout)
    current_pkgs = extract_packages(req_file.read_text(encoding="utf-8"))

    assert current_pkgs == exported_pkgs, (
        "requirements.txt está fora de sincronia com uv.lock! "
        "Execute: python -m uv export --no-dev --no-hashes --output-file requirements.txt"
    )
