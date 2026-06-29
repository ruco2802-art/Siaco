# -*- coding: utf-8 -*-
"""
Calculadora de Oferta Económica — SIACO v3.0
Metodología APU (IDU/INVIAS) con constantes oficiales 2026.
Fuente: Decretos 1469 y 1470 del 29 de diciembre de 2025.
"""

# ── Constantes oficiales 2026 ────────────────────────────────────────────────
SMMLV_2026               = 1_750_905          # Decreto 1469/2025
AUXILIO_TRANSPORTE_2026  = 249_095             # Decreto 1470/2025
SALARIO_INTEGRAL_MINIMO  = SMMLV_2026 * 13    # 10 SMMLV + factor 30%

# Factores prestacionales de referencia APU 2026 (fuente: gerencie.com / presucosto.com)
FACTOR_PRESTACIONAL_CON_AUXILIO = 0.5238  # trabajadores <= 2 SMMLV (con auxilio transporte)
FACTOR_PRESTACIONAL_SIN_AUXILIO = 0.4540  # trabajadores >  2 SMMLV

# ── Tablas de cargas ─────────────────────────────────────────────────────────
CARGAS_PRESTACIONALES = {
    "cesantias":           0.0833,
    "intereses_cesantias": 0.0100,
    "prima_servicios":     0.0833,
    "vacaciones":          0.0417,
    "dotacion":            0.0300,
}

SEGURIDAD_SOCIAL_EMPLEADOR = {
    "salud":       0.0850,
    "pension":     0.1200,
    "arl_nivel_1": 0.00522,   # administrativo / comercial
    "arl_nivel_2": 0.01044,   # tecnológico
    "arl_nivel_3": 0.02436,   # agrícola / transporte
    "arl_nivel_4": 0.04350,   # construcción edificaciones
    "arl_nivel_5": 0.06960,   # obras mineras / explosivos
}

PARAFISCALES = {
    "sena":              0.0200,
    "icbf":              0.0300,
    "caja_compensacion": 0.0400,
}

# ── Parámetros metodología APU ───────────────────────────────────────────────
METODOLOGIA_APU = {
    "horas_productivas_mes": 182,    # horas efectivas pagadas por mes
    "tpnl":                  0.225,  # Tiempo Pagado No Laborado
    "mayor_valor_prestacional": 0.1472,
}


class CalculadoraAPU:
    """
    Calculadora de Análisis de Precios Unitarios para contratos públicos colombianos.
    Constantes oficiales 2026 (Decretos 1469 y 1470).
    """

    # ── 1. Costo real mensual por trabajador ─────────────────────────────────
    def calcular_costo_real_trabajador(
        self, salario_basico: float, nivel_riesgo: int = 4
    ) -> dict:
        """
        Costo mensual total del empleador para un trabajador.
        Incluye prestaciones, parafiscales y seguridad social empleador.
        """
        arl_key = f"arl_nivel_{nivel_riesgo}"
        arl_pct = SEGURIDAD_SOCIAL_EMPLEADOR.get(arl_key, SEGURIDAD_SOCIAL_EMPLEADOR["arl_nivel_4"])

        aplica_auxilio = salario_basico <= 2 * SMMLV_2026
        aux_transporte = AUXILIO_TRANSPORTE_2026 if aplica_auxilio else 0.0

        # Base para cesantías/prima/int_ces incluye auxilio de transporte
        base_con_aux = salario_basico + aux_transporte

        desglose = {
            "salud_empleador":      round(salario_basico * SEGURIDAD_SOCIAL_EMPLEADOR["salud"]),
            "pension_empleador":    round(salario_basico * SEGURIDAD_SOCIAL_EMPLEADOR["pension"]),
            "arl":                  round(salario_basico * arl_pct),
            "cesantias":            round(base_con_aux * CARGAS_PRESTACIONALES["cesantias"]),
            "intereses_cesantias":  round(base_con_aux * CARGAS_PRESTACIONALES["intereses_cesantias"]),
            "prima_servicios":      round(base_con_aux * CARGAS_PRESTACIONALES["prima_servicios"]),
            "vacaciones":           round(salario_basico * CARGAS_PRESTACIONALES["vacaciones"]),
            "dotacion":             round(salario_basico * CARGAS_PRESTACIONALES["dotacion"]),
            "sena":                 round(salario_basico * PARAFISCALES["sena"]),
            "icbf":                 round(salario_basico * PARAFISCALES["icbf"]),
            "caja_compensacion":    round(salario_basico * PARAFISCALES["caja_compensacion"]),
        }

        total_cargas = sum(desglose.values())
        costo_total  = salario_basico + aux_transporte + total_cargas
        factor_pct   = round((total_cargas / salario_basico) * 100, 2) if salario_basico else 0.0

        return {
            "salario_basico":           round(salario_basico),
            "auxilio_transporte":       round(aux_transporte),
            "costo_mensual_empleador":  round(costo_total),
            "factor_prestacional":      factor_pct,
            "desglose":                 desglose,
            "nivel_riesgo":             nivel_riesgo,
            # Legacy key para compatibilidad interna
            "costo_total_mes":          round(costo_total),
        }

    # ── 2. Valor hora APU (metodología IDU/INVIAS) ───────────────────────────
    def calcular_valor_hora_apu(
        self, salario_basico: float, nivel_arl: int = 4
    ) -> dict:
        """
        Calcula el valor de la hora-hombre para presupuestos de construcción
        según metodología IDU/INVIAS 2026.
        TPNL: Tiempo Pagado No Laborado (22.5 %).
        MVP:  Mayor Valor Prestacional (14.72 %).
        """
        arl_key = f"arl_nivel_{nivel_arl}"
        arl_pct = SEGURIDAD_SOCIAL_EMPLEADOR.get(arl_key, SEGURIDAD_SOCIAL_EMPLEADOR["arl_nivel_4"])

        aplica_auxilio = salario_basico <= SMMLV_2026 * 2
        auxilio        = AUXILIO_TRANSPORTE_2026 if aplica_auxilio else 0.0
        base_con_aux   = salario_basico + auxilio

        salud        = salario_basico * 0.085
        pension      = salario_basico * 0.12
        cesantias    = base_con_aux * 0.0833
        int_ces      = base_con_aux * 0.01
        prima        = base_con_aux * 0.0833
        vacaciones   = salario_basico * 0.0417
        dotacion     = salario_basico * 0.03
        sena         = salario_basico * 0.02
        icbf         = salario_basico * 0.03
        caja         = salario_basico * 0.04
        arl_valor    = salario_basico * arl_pct

        costo_mes = (
            salario_basico + auxilio
            + salud + pension + cesantias + int_ces + prima
            + vacaciones + dotacion + sena + icbf + caja + arl_valor
        )

        horas_mes   = METODOLOGIA_APU["horas_productivas_mes"]
        tpnl        = METODOLOGIA_APU["tpnl"]
        mvp         = METODOLOGIA_APU["mayor_valor_prestacional"]

        valor_hora_base = costo_mes / horas_mes
        valor_hora_apu  = valor_hora_base * (1 + tpnl + mvp)

        return {
            "salario_basico":          round(salario_basico),
            "auxilio_transporte":      round(auxilio),
            "costo_mensual_empleador": round(costo_mes),
            "factor_prestacional":     round((costo_mes / salario_basico - 1) * 100, 2),
            "valor_hora_nomina":       round(salario_basico / 220),
            "valor_hora_apu":          round(valor_hora_apu),
            "desglose": {
                "salud_empleador":      round(salud),
                "pension_empleador":    round(pension),
                "arl":                  round(arl_valor),
                "cesantias":            round(cesantias),
                "intereses_cesantias":  round(int_ces),
                "prima_servicios":      round(prima),
                "vacaciones":           round(vacaciones),
                "dotacion":             round(dotacion),
                "sena":                 round(sena),
                "icbf":                 round(icbf),
                "caja_compensacion":    round(caja),
            },
        }

    # ── 3. Mano de obra total ────────────────────────────────────────────────
    def calcular_mano_obra(self, personal: list[dict]) -> dict:
        """
        Costo total de mano de obra con prestaciones para una lista de cargos.
        personal: [{cargo, salario, cantidad, dias, nivel_riesgo=4}]
        """
        items = []
        total = 0.0
        for p in personal:
            salario  = float(p.get("salario", 0))
            cantidad = int(p.get("cantidad", 1))
            dias     = float(p.get("dias", 30))
            riesgo   = int(p.get("nivel_riesgo", 4))
            costo_mes = self.calcular_costo_real_trabajador(salario, riesgo)["costo_total_mes"]
            costo_periodo = costo_mes * cantidad * (dias / 30)
            hora_apu = self.calcular_valor_hora_apu(salario, riesgo)["valor_hora_apu"]
            items.append({
                "cargo":               p.get("cargo", "Sin nombre"),
                "salario_basico":      round(salario),
                "cantidad":            cantidad,
                "dias":                dias,
                "costo_mes_unitario":  round(costo_mes),
                "valor_hora_apu":      round(hora_apu),
                "costo_total":         round(costo_periodo),
                "factor_prestacional": round((costo_mes / salario - 1) * 100, 2) if salario else 0,
            })
            total += costo_periodo

        return {"items": items, "subtotal": round(total)}

    # ── 4. Materiales ────────────────────────────────────────────────────────
    def calcular_materiales(self, items: list[dict]) -> dict:
        """
        Subtotal de materiales. IVA 19% solo si el ítem tiene iva=True.
        items: [{nombre, unidad, cantidad, precio_unitario, iva=False}]
        """
        resultado        = []
        subtotal_sin_iva = 0.0
        total_iva        = 0.0
        for item in items:
            cantidad    = float(item.get("cantidad", 0))
            precio      = float(item.get("precio_unitario", 0))
            aplica_iva  = bool(item.get("iva", False))
            subtotal    = cantidad * precio
            iva_item    = subtotal * 0.19 if aplica_iva else 0.0
            resultado.append({
                "nombre":          item.get("nombre", ""),
                "unidad":          item.get("unidad", "und"),
                "cantidad":        cantidad,
                "precio_unitario": round(precio),
                "subtotal":        round(subtotal),
                "iva":             round(iva_item),
                "total":           round(subtotal + iva_item),
            })
            subtotal_sin_iva += subtotal
            total_iva        += iva_item

        return {
            "items":            resultado,
            "subtotal_sin_iva": round(subtotal_sin_iva),
            "total_iva":        round(total_iva),
            "subtotal":         round(subtotal_sin_iva + total_iva),
        }

    # ── 5. AIU ───────────────────────────────────────────────────────────────
    def calcular_aiu(
        self,
        costos_directos:  float,
        admin_pct:        float = 0.12,
        imprevistos_pct:  float = 0.03,
        utilidad_pct:     float = 0.08,
    ) -> dict:
        """
        Administración, Imprevistos y Utilidad sobre costos directos.
        Porcentajes en decimal (0.12 = 12 %).
        """
        admin       = costos_directos * admin_pct
        imprevistos = costos_directos * imprevistos_pct
        utilidad    = costos_directos * utilidad_pct
        total_aiu   = admin + imprevistos + utilidad

        return {
            "administracion":   round(admin),
            "imprevistos":      round(imprevistos),
            "utilidad":         round(utilidad),
            "total_aiu":        round(total_aiu),
            "porcentaje_total": round((admin_pct + imprevistos_pct + utilidad_pct) * 100, 2),
            "admin_pct":        round(admin_pct * 100, 2),
            "imprevistos_pct":  round(imprevistos_pct * 100, 2),
            "utilidad_pct":     round(utilidad_pct * 100, 2),
        }

    # ── 6. Pólizas ───────────────────────────────────────────────────────────
    def calcular_polizas(self, valor_contrato: float, plazo_meses: int = 6) -> dict:
        """
        Estimado de primas de pólizas obligatorias en contratación pública colombiana.
        Tarifas reales varían por aseguradora y perfil de riesgo.
        """
        TASA_SERIEDAD     = 0.003
        TASA_CUMPLIMIENTO = 0.005
        TASA_RESPONSAB    = 0.008
        TASA_ESTABILIDAD  = 0.004

        seriedad      = (valor_contrato * 0.10) * TASA_SERIEDAD * (3 / 12)
        cumplimiento  = (valor_contrato * 0.30) * TASA_CUMPLIMIENTO * (plazo_meses / 12)
        estabilidad   = (valor_contrato * 0.20) * TASA_ESTABILIDAD
        responsab_civ = (valor_contrato * 0.05) * TASA_RESPONSAB * (plazo_meses / 12)
        total         = seriedad + cumplimiento + estabilidad + responsab_civ

        return {
            "seriedad":              round(seriedad),
            "cumplimiento":          round(cumplimiento),
            "estabilidad":           round(estabilidad),
            "responsabilidad_civil": round(responsab_civ),
            "total_estimado":        round(total),
            "nota": "Prima estimada. Tarifa real depende de aseguradora y riesgo.",
        }

    # ── 7. Precio oferta completo ────────────────────────────────────────────
    def calcular_precio_oferta(
        self,
        materiales:      list[dict],
        personal:        list[dict],
        equipos:         list[dict],
        admin_pct:       float = 0.12,
        imprevistos_pct: float = 0.03,
        utilidad_pct:    float = 0.08,
        incluir_polizas: bool  = True,
        plazo_meses:     int   = 6,
    ) -> dict:
        """
        Precio mínimo y sugerido de una oferta económica.
        Incluye AIU, pólizas estimadas y márgenes.
        """
        mat = self.calcular_materiales(materiales)
        mo  = self.calcular_mano_obra(personal)
        eq  = self._calcular_equipos(equipos)

        subtotal_directo = mat["subtotal"] + mo["subtotal"] + eq["subtotal"]
        aiu_data = self.calcular_aiu(subtotal_directo, admin_pct, imprevistos_pct, utilidad_pct)
        polizas  = self.calcular_polizas(subtotal_directo + aiu_data["total_aiu"], plazo_meses)

        precio_minimo = subtotal_directo + aiu_data["total_aiu"]
        if incluir_polizas:
            precio_minimo += polizas["total_estimado"]

        precio_sugerido = round(precio_minimo * 1.05)
        utilidad_pesos  = aiu_data["utilidad"]
        margen_pct      = round(utilidad_pesos / precio_minimo * 100, 2) if precio_minimo else 0.0
        iva_si_aplica   = round(precio_minimo * 0.19)

        return {
            "costos_directos": {
                "materiales": mat["subtotal"],
                "mano_obra":  mo["subtotal"],
                "equipos":    eq["subtotal"],
                "subtotal":   subtotal_directo,
            },
            "aiu":             aiu_data,
            "polizas_estimadas": polizas["total_estimado"] if incluir_polizas else 0,
            "precio_minimo":   round(precio_minimo),
            "precio_sugerido": precio_sugerido,
            "resumen": {
                "total_sin_iva":       round(precio_minimo),
                "iva_si_aplica":       iva_si_aplica,
                "total_con_iva":       round(precio_minimo + iva_si_aplica),
                "utilidad_proyectada": utilidad_pesos,
                "margen_utilidad_pct": margen_pct,
            },
            "detalles": {
                "materiales_items": mat["items"],
                "mano_obra_items":  mo["items"],
                "equipos_items":    eq["items"],
                "polizas":          polizas if incluir_polizas else {},
            },
        }

    # ── 8. Flujo de caja (metodología contratos públicos) ────────────────────
    def calcular_flujo_caja(
        self,
        valor_contrato:  float,
        anticipo_pct:    float = 0.30,
        plazo_meses:     int   = 6,
        costos_directos: float = 0.0,
        aiu_pct:         float = 0.23,
        forma_pago:      str   = "actas_mensuales",
    ) -> dict:
        """
        Proyección mensual de flujo de caja según mecánica real de contratos públicos:
        1. Día 0: entidad entrega anticipo.
        2. Mensualmente: acta de obra → entidad descuenta amortización proporcional del anticipo.
        3. Contratista recibe: valor_acta_bruta - amortizacion_anticipo.
        """
        anticipo              = valor_contrato * anticipo_pct
        valor_sin_anticipo    = valor_contrato - anticipo
        acta_bruta_mensual    = valor_contrato / plazo_meses   # lo que se le factura a la entidad
        amortizacion_mensual  = anticipo / plazo_meses         # lo que la entidad retiene por acta
        # Costo mensual a ejecutar (costos directos; si no se pasa, se estima del valor contrato)
        costo_mensual = (costos_directos / plazo_meses) if costos_directos > 0 \
                        else (valor_contrato / (1 + aiu_pct)) / plazo_meses

        flujo            = []
        saldo_acumulado  = anticipo   # el anticipo llega antes de empezar la ejecución

        for mes in range(1, plazo_meses + 1):
            ingreso_mes  = acta_bruta_mensual   # acta bruta que factura el contratista
            egreso_mes   = costo_mensual
            # Flujo neto = ingreso bruto - amortización anticipo - costos
            flujo_neto   = ingreso_mes - amortizacion_mensual - egreso_mes
            saldo_acumulado += flujo_neto

            flujo.append({
                "mes":         mes,
                "descripcion": f"Mes {mes}",
                "ingresos": {
                    "anticipo":       round(anticipo) if mes == 0 else 0,
                    "acta_cobrada":   round(ingreso_mes),
                    "total_ingresos": round(ingreso_mes),
                },
                "egresos": {
                    "costos_directos": round(egreso_mes),
                    "total_egresos":   round(egreso_mes),
                },
                "amortizacion_anticipo": round(amortizacion_mensual),
                "flujo_neto_mes":        round(flujo_neto),
                "saldo_acumulado":       round(saldo_acumulado),
                "alerta":               saldo_acumulado < 0,
            })

        saldos = [f["saldo_acumulado"] for f in flujo]
        saldo_minimo = min(saldos, default=0)
        capital_adicional = abs(min(saldo_minimo, 0))

        resumen_txt = (
            f"Con anticipo del {int(anticipo_pct*100)}%, recibe ${anticipo:,.0f} al inicio. "
            f"Cobra actas de ${acta_bruta_mensual:,.0f}/mes "
            f"descontando ${amortizacion_mensual:,.0f} de amortización. "
            + (
                f"⚠️ Requiere capital adicional de ${capital_adicional:,.0f}."
                if saldo_minimo < 0
                else "✅ Flujo positivo durante toda la ejecución."
            )
        )

        return {
            "anticipo_recibido":             round(anticipo),
            "anticipo_pct":                  round(anticipo_pct * 100, 1),
            "valor_obra_sin_anticipo":        round(valor_sin_anticipo),
            "acta_bruta_mensual":            round(acta_bruta_mensual),
            "amortizacion_anticipo_por_acta": round(amortizacion_mensual),
            "acta_neta_mensual":             round(acta_bruta_mensual - amortizacion_mensual),
            "costo_mensual_estimado":        round(costo_mensual),
            "flujo_mensual":                 flujo,
            "capital_trabajo_adicional":     round(capital_adicional),
            "alerta_deficit":               saldo_minimo < 0,
            "resumen":                       resumen_txt,
            # Legacy alias para compatibilidad
            "proyeccion": flujo,
            "alertas":   [f"Mes {f['mes']}: saldo negativo — necesita ${abs(f['saldo_acumulado']):,} de capital"
                          for f in flujo if f["alerta"]],
        }

    # ── 9. Verificar viabilidad ──────────────────────────────────────────────
    def verificar_viabilidad_presupuesto(
        self, precio_minimo: float, presupuesto_oficial: float
    ) -> dict:
        """
        Compara precio mínimo calculado vs presupuesto oficial publicado.
        Retorna concepto VIABLE / AJUSTADO / INVIABLE.
        """
        diferencia = presupuesto_oficial - precio_minimo
        margen_pct = round(diferencia / presupuesto_oficial * 100, 2) if presupuesto_oficial else 0.0

        if diferencia < 0:
            concepto = "INVIABLE"
            recomendacion = (
                f"El presupuesto oficial (${presupuesto_oficial:,.0f}) es menor que su precio mínimo "
                f"(${precio_minimo:,.0f}). Debe reducir costos en ${abs(diferencia):,.0f} "
                f"({abs(margen_pct):.1f}%) para participar sin pérdidas."
            )
        elif margen_pct < 8:
            concepto = "AJUSTADO"
            recomendacion = (
                f"Puede participar pero el margen es estrecho ({margen_pct:.1f}%). "
                "Revise materiales y equipos de mayor costo. "
                "Considere ajustar el porcentaje de utilidad."
            )
        else:
            concepto = "VIABLE"
            recomendacion = (
                f"El presupuesto oficial deja un margen de {margen_pct:.1f}% sobre su precio mínimo. "
                "Puede presentar una oferta competitiva y rentable."
            )

        return {
            "viable":                concepto != "INVIABLE",
            "diferencia":            round(diferencia),
            "margen_disponible_pct": margen_pct,
            "concepto":              concepto,
            "recomendacion":         recomendacion,
            "precio_minimo":         round(precio_minimo),
            "presupuesto_oficial":   round(presupuesto_oficial),
        }

    # ── Interno: equipos ─────────────────────────────────────────────────────
    def _calcular_equipos(self, equipos: list[dict]) -> dict:
        """Costo total de equipos y herramientas."""
        items = []
        total = 0.0
        for eq in equipos:
            costo_dia = float(eq.get("costo_dia", 0))
            dias      = float(eq.get("dias", 1))
            subtotal  = costo_dia * dias
            items.append({
                "nombre":    eq.get("nombre", ""),
                "costo_dia": round(costo_dia),
                "dias":      dias,
                "subtotal":  round(subtotal),
            })
            total += subtotal
        return {"items": items, "subtotal": round(total)}
