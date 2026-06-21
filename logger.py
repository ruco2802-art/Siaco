# -*- coding: utf-8 -*-
import logging
from datetime import datetime
from pathlib import Path


def setup_logger(nombre: str = "siaco") -> logging.Logger:
    """
    Configura logger con salida simultánea a archivo y consola.
    Niveles: DEBUG (chunks RAG), INFO (búsquedas/análisis), WARNING (API lenta >10s), ERROR (fallo API).
    """
    logs_dir = Path("./logs")
    logs_dir.mkdir(exist_ok=True)

    fecha = datetime.now().strftime("%Y-%m-%d")
    log_file = logs_dir / f"siaco_{fecha}.log"

    logger = logging.getLogger(nombre)
    if logger.handlers:
        return logger

    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger
