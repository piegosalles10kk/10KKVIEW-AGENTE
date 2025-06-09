# 10KK VIEW AGENTE

## 📌 **Pré-requisitos**
Antes de iniciar, certifique-se de que tem o seguinte instalado:
- **Python 3.8 ou superior** ([Baixar aqui](https://www.python.org/downloads/))
- **Pip** (já incluído no Python)

## ⚙️ **Instalação**
### 1️⃣ **Criar e ativar um ambiente virtual**
Abra o terminal e execute:

```sh
python -m venv venv
```

### 2️⃣ **Ativar ambiente virtual**
- **No Windows**
 
```sh
venv\Scripts\activate
```
- **No Mac/Linux**

```sh
source venv/bin/activate
```

### 3️⃣ **Instalar dependências**
Com a venv ativada, execute:

```sh
pip install -r requirements.txt
```

### 🚀 **Rodando o aplicativo**
Após instalar as depenências, execute:

```sh
python "10KK VIEW.py"
```

### 💻 **Gerar um .exe (Opcional)**
Caso prefira criar um executavél, utilize o PyInstaller:

```sh
pip install pyinstaller
pyinstaller --onefile --noconsole --icon="icone_agente.ico" --hidden-import win32service "10KK VIEW.py"
```
