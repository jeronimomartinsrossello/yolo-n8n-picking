# Contribuir

1. Haz un fork y crea una rama desde `main`: `git checkout -b feat/mi-cambio`.
2. Instala el entorno de desarrollo:
   ```bash
   python -m venv .venv
   .venv/Scripts/activate      # Windows  (Linux/macOS: source .venv/bin/activate)
   pip install -r requirements-dev.txt
   ```
3. Antes de abrir el PR, comprueba que pasan lint y tests (lo mismo que ejecuta la CI):
   ```bash
   ruff check . && ruff format --check .
   pytest
   ```
4. Usa mensajes de commit en formato [Conventional Commits](https://www.conventionalcommits.org/)
   (`feat:`, `fix:`, `docs:`, `test:`, `ci:`, `chore:`).
5. Abre el Pull Request rellenando la plantilla.

**No subas nunca** tu `.env`, URLs de webhook reales ni pesos de modelos (`*.pt`).
