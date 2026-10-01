# -*- coding: utf-8 -*-
"""
src/perfil.py — esquema canónico de PerfilEmpresa.

ÚNICA fuente de verdad: el frontend y el pipeline importan desde aquí.
No dupliques estas clases en evaluator.py, routers/perfil.py ni en ningún otro módulo.

Convención semántica — bloque jurídico:
  True SIEMPRE significa condición favorable para ofertar, sin excepción.
  Ejemplos: sin_inhabilidades=True → no tiene inhabilidades (puede ofertar).
            sin_redam=True → no figura en REDAM (puede ofertar).
  Esta convención elimina la ambigüedad entre "tengo el certificado" y "estoy
  reportado"; todos los evaluadores y el skill generacion_criterios.md la asumen.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, ValidationError, model_validator


# ─── Capacidad financiera ──────────────────────────────────────────────────

class PerfilFinanciero(BaseModel):
    # Indicadores de liquidez y solvencia (requeridos por Res. 539/540/541)
    indice_liquidez: float | None = None
    indice_endeudamiento: float | None = None
    cobertura_intereses: float | None = None
    # Balance básico
    capital_trabajo: float | None = None
    activo_corriente: float | None = None
    pasivo_corriente: float | None = None
    patrimonio_neto: float | None = None
    # Rentabilidad
    renta_operacional: float | None = None
    ebitda: float | None = None
    rentabilidad_patrimonio: float | None = None  # ROE (Utilidad neta / Patrimonio)
    rentabilidad_activo: float | None = None      # ROA (Utilidad operacional / Activo total)
    roe: float | None = None  # alias explícito cuando el pliego usa "ROE" como término
    roa: float | None = None  # alias explícito cuando el pliego usa "ROA" como término
    # Capacidad residual (Factor K)
    ingresos_operacionales_ultimos_5_anos: list[float] = Field(default_factory=list)
    saldos_contratos_en_ejecucion: float | None = None  # Σ(valor × % pendiente)
    numero_profesionales_vinculados: int | None = None


# ─── Experiencia ───────────────────────────────────────────────────────────

class PerfilExperiencia(BaseModel):
    valor_acumulado: float | None = None
    valor_individual_max: float | None = None
    objetos_similares: list[str] = Field(default_factory=list)
    codigos_unspsc: list[str] = Field(default_factory=list)
    contratos_acreditados: int | None = None
    antiguedad_meses: int | None = None


# ─── Habilitación jurídica ─────────────────────────────────────────────────

class PerfilJuridico(BaseModel):
    # Documentos de existencia y representación
    rup_en_firme: bool | None = None
    rup_fecha_expedicion: str | None = None        # ISO-8601 o "YYYY-MM-DD"
    camara_comercio: bool | None = None
    camara_comercio_fecha: str | None = None
    rut_vigente: bool | None = None
    rut_fecha: str | None = None
    # Paz y salvos
    paz_y_salvo_parafiscales: bool | None = None
    paz_y_salvo_seguridad_social: bool | None = None
    paz_y_salvo_impuestos: bool | None = None
    paz_salvo_municipal: bool | None = None
    paz_salvo_municipal_fecha: str | None = None
    # Antecedentes y registros (True = condición favorable, ver convención del módulo)
    sin_inhabilidades: bool | None = None
    sin_antecedentes_disciplinarios: bool | None = None
    sin_antecedentes_penales: bool | None = None
    sin_antecedentes_fiscales: bool | None = None
    sin_antecedentes_fiscales_fecha: str | None = None
    sin_redam: bool | None = None
    sin_redam_fecha: str | None = None
    sin_medidas_correctivas: bool | None = None
    # Declaraciones habilitantes firmadas por el proponente
    sin_insolvencia: bool | None = None                  # Ley 1116/2006
    objeto_social_compatible: bool | None = None         # compatible con el objeto del contrato
    sin_conflicto_interes: bool | None = None
    sin_estudios_diseno_previos: bool | None = None      # no realizó estudios/diseños de la obra
    # Otros
    garantia_seriedad: bool | None = None


# ─── Documentos [D27] ──────────────────────────────────────────────────────
#
# El paso 3 de la cadena del servicio —qué exige el pliego · si la empresa
# cumple · **qué le falta** · si alcanza a conseguirlo— no existía. Medido en
# Paicol: de los requisitos habilitantes documentales sin dato, **el 100% eran
# «no preguntado»**. Ninguno decía «le falta esto»; todos decían «no sabemos».
# El perfil no tenía campo para ellos, así que el sistema no podía producir ni
# un hallazgo documental, que es justamente el valor del análisis.
#
# DOS REGLAS QUE ESTE BLOQUE NO PUEDE ROMPER:
#
# 1. **Cada campo responde SOLO lo que pregunta [D32].** «Tiene el certificado
#    de existencia» NO responde «la sociedad dura más que el plazo del contrato
#    más un año»; «está al día en seguridad social» NO responde «no tiene
#    obligación de aportes por no tener personal a cargo». Si un requisito
#    necesita un dato que el campo no contiene, se queda en `no_preguntado`.
#    Inferirlo produciría un CUMPLE falso sobre un habilitante, que es el error
#    más caro del sistema.
#
# 2. **`tiene` sin `fecha_expedicion` no alcanza cuando el pliego exige
#    vigencia.** Varios requisitos piden documentos expedidos con menos de 30
#    días. Con `tiene=True` y sin fecha, lo honesto es decir que falta la
#    fecha, no dar por vigente el documento [I10].


class Documento(BaseModel):
    """
    Un documento del expediente de la empresa.

    `tiene` es la respuesta del cliente y los tres valores significan cosas
    distintas, ninguna sustituible por otra:

        None   no se le preguntó, o no respondió  -> `dato_faltante`
        False  responde que NO lo tiene           -> `no_cumple`: HALLAZGO
        True   responde que SÍ lo tiene           -> `cumple`, salvo vigencia

    `fecha_expedicion` en ISO (`YYYY-MM-DD`). Va vacía mientras no se pregunte:
    un documento sin fecha no se presume vigente.
    """
    tiene: bool | None = None
    fecha_expedicion: str | None = None

    def dias_desde_expedicion(self, referencia: date | None = None) -> int | None:
        """
        Días transcurridos desde la expedición, o None si no hay fecha o no es
        una fecha válida. **Nunca lanza**: una fecha mal escrita por el cliente
        no puede tumbar una evaluación, y devolver None deja el requisito en
        `dato_faltante`, que es lo correcto.
        """
        if not self.fecha_expedicion:
            return None
        try:
            expedido = date.fromisoformat(str(self.fecha_expedicion)[:10])
        except (TypeError, ValueError):
            return None
        return (( referencia or date.today()) - expedido).days


class PerfilDocumental(BaseModel):
    """
    Los documentos que los dos pliegos medidos (Paicol y Ternera) exigen como
    requisito habilitante. Son los campos BÁSICOS del perfil: aparecen en
    ambos, así que no son complementarios de un proceso concreto.

    Lo que cada uno responde, y **sólo** eso:

    - `rup` — que el RUP esté vigente y en firme. NO responde qué está
      inscrito en él (experiencia, indicadores, condición Mipyme): eso son
      otras preguntas sobre el mismo documento.
    - `existencia_representacion` — que tenga el certificado. **NO responde
      cuánto dura la sociedad**, que es lo que los dos pliegos preguntan de
      verdad; para eso hace falta un campo de duración que todavía no existe.
    - `estados_financieros` — que tenga los estados financieros del último
      ejercicio. NO responde el valor de ningún indicador: ésos están en
      `PerfilFinanciero`.
    - `seguridad_social` — que tenga la certificación de pagos al sistema. **NO
      responde** que esté exento de cotizar, ni que no tenga personal a cargo,
      ni el régimen pensional del representante: son declaraciones distintas.
    - `documento_identidad` — la cédula del representante legal.
    - `subcontratacion` — que tenga autorización del contrato principal para
      subcontratar. NO responde la obligación de informar subcontratos durante
      la ejecución, que es una regla del contrato y no un documento.
    """
    rup: Documento = Field(default_factory=Documento)
    existencia_representacion: Documento = Field(default_factory=Documento)
    estados_financieros: Documento = Field(default_factory=Documento)
    seguridad_social: Documento = Field(default_factory=Documento)
    documento_identidad: Documento = Field(default_factory=Documento)
    subcontratacion: Documento = Field(default_factory=Documento)

    # Condición, no documento: la capacidad para obligarse. El pliego la exige
    # en dos momentos —presentar la oferta y celebrar el contrato— y una sola
    # respuesta cubre los dos.
    capacidad_juridica: bool | None = None

    # [D34] Hasta cuándo está constituida la sociedad, en ISO (`YYYY-MM-DD`).
    #
    # Es lo que de verdad preguntan los dos pliegos sobre la existencia y
    # representación: *«deberán acreditar que su duración no será inferior a la
    # del plazo del Contrato y un año más»*. Tener el certificado de Cámara de
    # Comercio NO lo contesta [D32]; esta fecha sí, y está en ese mismo
    # certificado, así que al cliente no le cuesta nada responderla.
    #
    # La comparación es contra el PLAZO DEL CONTRATO más un año, y ese plazo
    # sale del pliego, no del perfil. Hoy el pipeline **no lo extrae**: está en
    # el texto de Paicol («DOS MESES (02)») pero dentro de una tabla que el
    # parser partió, y ningún campo estructurado lo recoge — `plazo_meses`
    # existe como variable declarada en `resolucion_variables.py` y nada la
    # puebla. Mientras siga así, este campo no resuelve ningún requisito, pero
    # el estado que produce cambia de sitio la culpa: deja de ser «no se le
    # preguntó al cliente» y pasa a ser «falta el plazo del pliego», que es
    # tarea del operador.
    duracion_sociedad_hasta: str | None = None

    def esta_vacio(self) -> bool:
        """True si no se respondió nada: el bloque no aporta sobre `None`."""
        return (self.capacidad_juridica is None
                and all(getattr(self, c).tiene is None
                        and getattr(self, c).fecha_expedicion is None
                        for c in _CAMPOS_DOCUMENTO))


_CAMPOS_DOCUMENTO: tuple[str, ...] = (
    "rup", "existencia_representacion", "estados_financieros",
    "seguridad_social", "documento_identidad", "subcontratacion",
)


# ─── Capacidad técnica ─────────────────────────────────────────────────────

class PerfilTecnico(BaseModel):
    personal_disponible: int | None = None
    equipos: list[str] = Field(default_factory=list)
    certificaciones: list[str] = Field(default_factory=list)
    titulo_profesional: Literal["arquitecto", "ingeniero", "ninguno"] | None = None
    porcentaje_empleados_colombianos: float | None = None  # 0-100


# ─── Componente social ─────────────────────────────────────────────────────

class PerfilSocial(BaseModel):
    porcentaje_mujeres_nomina: float | None = None
    porcentaje_discapacidad: float | None = None
    personas_reincorporadas: int | None = None
    poblacion_etnica: bool | None = None


# ─── Perfil canónico ───────────────────────────────────────────────────────

# De dónde viene cada documento en los perfiles anteriores a [D27]:
# (campo booleano del bloque jurídico, campo de fecha o None si no se pedía).
#
# `existencia_representacion` viene de `camara_comercio` porque el certificado
# de Cámara de Comercio ES el medio de prueba de la existencia y representación
# legal — el catálogo los une en el mismo objeto.
_LEGADO_A_DOCUMENTO: dict[str, tuple[str, str | None]] = {
    "rup": ("rup_en_firme", "rup_fecha_expedicion"),
    "existencia_representacion": ("camara_comercio", "camara_comercio_fecha"),
    "seguridad_social": ("paz_y_salvo_seguridad_social", None),
}


class PerfilEmpresa(BaseModel):
    # Identificación
    nombre: str
    nit: str | None = None
    sector: str | None = None
    municipio_domicilio: str | None = None
    departamento_domicilio: str | None = None
    es_mipyme: bool = False
    tamano_empresa: Literal["micro", "pequena", "mediana", "grande"] | None = None
    es_empresa_de_mujeres: bool = False
    es_proponente_plural: bool = False  # True solo para consorcios/uniones temporales
    # Bloques de capacidad
    financiero: PerfilFinanciero | None = None
    experiencia: PerfilExperiencia | None = None
    juridico: PerfilJuridico | None = None
    tecnico: PerfilTecnico | None = None
    social: PerfilSocial | None = None
    # [D27] Los documentos. Bloque nuevo: los perfiles guardados antes no lo
    # traen, y `cargar_perfil()` lo rellena desde los campos sueltos del bloque
    # jurídico para que un perfil viejo no pierda lo que ya había respondido.
    documentos: PerfilDocumental | None = None

    @model_validator(mode="after")
    def _migrar_documentos(self):
        """
        [D27] Rellena el bloque documental desde los campos sueltos del bloque
        jurídico, que es donde vivían tres de los seis documentos antes de que
        este bloque existiera. Un perfil guardado antes NO pierde lo que
        respondió.

        Va en el modelo y no en `cargar_perfil()` a propósito: si viviera en la
        función, cualquier otro camino de construcción —`model_validate()`, un
        test, un router que arme el perfil a mano— se saltaría la migración y
        el mismo perfil daría veredictos distintos según cómo se hubiera
        cargado. Ese fue exactamente el fallo al escribirlo.

        Sólo rellena lo que el bloque nuevo deja vacío: si el cliente contestó
        el formulario nuevo, su respuesta manda sobre el campo antiguo.
        """
        if self.juridico is None:
            return self
        docs = self.documentos or PerfilDocumental()
        for destino, (campo_tiene, campo_fecha) in _LEGADO_A_DOCUMENTO.items():
            doc = getattr(docs, destino)
            if doc.tiene is None:
                doc.tiene = getattr(self.juridico, campo_tiene, None)
            if doc.fecha_expedicion is None and campo_fecha:
                doc.fecha_expedicion = getattr(self.juridico, campo_fecha, None)
        self.documentos = None if docs.esta_vacio() else docs
        return self


def cliente_id_activo(sesion: dict) -> str:
    """
    El cliente cuyo perfil de EMPRESA rige ahora mismo [D42a].

    Es el perfil que el operador eligió en el selector; si no eligió ninguno,
    el de su propia sesión. **Un solo sitio resuelve esta pregunta** para que
    la búsqueda, el análisis y el informe no puedan responderla distinto
    [I11]: antes cada router la resolvía por su cuenta.

    Vive aquí, con el esquema canónico, y no en el router: es lógica pura
    sobre un dict y así la pueden usar el pipeline y los tests sin arrastrar
    FastAPI.
    """
    return (sesion.get("perfil_activo")
            or sesion.get("cliente_id")
            or sesion.get("id")
            or "")


def ruta_perfil_cliente(cid: str, base_dir: str | None = None) -> Path:
    """
    **La ruta de la verdad** del perfil de EMPRESA de un cliente [D42c].

    `clientes/{cid}.json`, y no `clientes/{cid}/perfil.json`: ese otro archivo
    es el perfil de SESIÓN —`cliente_id`, `plan`, contacto— que escribe
    `auth.crear_cliente()` y lee el login. Son dos cosas distintas que
    conviven a propósito; lo que no puede pasar es confundirlas [D42b].

    Está aquí, en el esquema canónico, para que **todos los módulos deriven la
    ruta del mismo sitio** en vez de escribirla a mano cada uno.
    """
    base = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2] / "clientes"
    return base / f"{cid}.json"


def perfiles_disponibles(base_dir: str | None = None) -> list[dict]:
    """
    Los perfiles de EMPRESA guardados, para el selector [D42a].

    Lee sólo lo que el selector necesita —identificador, nombre, NIT y
    sector— sin validar el perfil entero: un perfil a medio llenar tiene que
    poder elegirse, y es justo lo que pasa mientras se está creando.

    Ignora `clientes/{cid}/` (directorios): ahí vive el perfil de SESIÓN, que
    es otra cosa [D42b].
    """
    import json as _json

    base = Path(base_dir) if base_dir else Path(__file__).resolve().parents[2] / "clientes"
    if not base.exists():
        return []
    salida: list[dict] = []
    for ruta in sorted(base.glob("*.json")):
        try:
            d = _json.loads(ruta.read_text("utf-8"))
        except Exception:
            continue
        if not isinstance(d, dict):
            continue
        salida.append({
            "cid": ruta.stem,
            "nombre": d.get("nombre") or ruta.stem,
            "nit": d.get("nit") or "",
            "sector": d.get("sector") or "",
            "es_ejemplo": bool((d.get("_meta") or {}).get("proposito")),
        })
    return salida


def cargar_perfil(data: dict) -> PerfilEmpresa:
    """
    Valida y construye el PerfilEmpresa desde un dict (leído de Supabase o disco).

    Si un bloque completo falta (financiero, juridico, etc.) el campo queda None;
    los requisitos de esa categoría recibirán estado 'dato_faltante' en el evaluador.
    Los campos desconocidos del dict se ignoran (migración progresiva).
    """
    try:
        perfil = PerfilEmpresa(**data)
    except ValidationError as exc:
        raise ValueError(
            f"Perfil de empresa inválido — corrígelo antes de continuar:\n{exc}"
        ) from exc

    return perfil
