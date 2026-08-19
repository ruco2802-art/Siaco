import os
import pandas as pd
from docx import Document

def convertir_a_texto():
    base_dir = "./biblioteca_normativa"

    for root, dirs, files in os.walk(base_dir):
        for file in files:
            file_path = os.path.join(root, file)
            txt_path = os.path.splitext(file_path)[0] + ".txt"

            # --- CONVERSIÓN DE EXCEL (.xlsx) ---
            if file.endswith(".xlsx") and not file.startswith("~$"):
                print(f"Procesando Excel: {file}")
                # sheet_name=None → todas las hojas como dict {nombre: DataFrame}
                hojas = pd.read_excel(file_path, sheet_name=None)
                with open(txt_path, "w", encoding="utf-8") as f:
                    for nombre_hoja, df in hojas.items():
                        f.write(f"## {nombre_hoja}\n\n")
                        f.write(df.fillna("—").to_markdown(index=False))
                        f.write("\n\n")
            
            # --- CONVERSIÓN DE WORD (.docx) ---
            elif file.endswith(".docx"):
                print(f"Procesando Word: {file}")
                doc = Document(file_path)
                texto = "\n".join([para.text for para in doc.paragraphs])
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(texto)
                    
    print("\n¡Conversión finalizada! Todos los archivos .txt están listos para SIACO.")

if __name__ == "__main__":
    convertir_a_texto()