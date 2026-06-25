# Garantiza que la raíz del proyecto esté en sys.path para que todos los
# routers puedan hacer `import config`, `import analizador`, etc. sin
# importar desde qué directorio de trabajo arranque el proceso (Railway, etc.)
import sys
from pathlib import Path

_root = Path(__file__).resolve().parent.parent
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))
