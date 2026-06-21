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
                df = pd.read_excel(file_path)
                with open(txt_path, "w", encoding="utf-8") as f:
                    f.write(df.to_string())
            
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