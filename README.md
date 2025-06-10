# 10KK VIEW AGENTE

## 📌 **Pré-requisitos**
Antes de iniciar, certifique-se de que tem o seguinte instalado:
- **Python 3.8 ou superior** ([Baixar aqui](https://www.python.org/downloads/))
- **Pip** (já incluído no Python)

## ⚙️ **Instalação**

### **Sem Python**
Caso escolha utilizar sem python, siga os seguintes passos:
- Abra a pasta **"10KK VIEW"**
- Abra o json chamado **config.json** que possui essa estrutura:
```json
{
    "SHARED_NETWORK_PATH": "",
    "COLLECTION_INTERVAL_SECONDS": 10,
    "MACHINE_ALIAS": ""
}
```
- Informe o caminho da pasta onde deseja armazenar o diretório de pastas do agente em **"SHARED_NETWORK_PATH"**
- Informe o tempo entre as coletas de dados em segundos dentro da variável **"COLLECTION_INTERVAL_SECONDS"**
- Informe o apelido da máquina em **"MACHINE_ALIAS"**
- Após configurar o diretório, execute o arquivo chamado "OpenHardwareMonitor.exe" dentro da pasta "OpenHardwareMonitor"
- Em seguida, execute o .exe chamado  10KK VIEW

### **Com Python**
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
## 🚀 **Configurando o aplicativo**
- Abra o json chamado **config.json** que possui essa estrutura:
```json
{
    "SHARED_NETWORK_PATH": "",
    "COLLECTION_INTERVAL_SECONDS": 10,
    "MACHINE_ALIAS": ""
}
```
- Informe o caminho da pasta onde deseja armazenar o diretório de pastas do agente em **"SHARED_NETWORK_PATH"**
- Informe o tempo entre as coletas de dados em segundos dentro da variável **"COLLECTION_INTERVAL_SECONDS"**
- Informe o apelido da máquina em **"MACHINE_ALIAS"**

## 🚀 **Rodando o aplicativo**
- Após instalar as depenências, execute o arquivo chamado "OpenHardwareMonitor.exe" dentro da pasta "OpenHardwareMonitor"
- Após inicializar o mesmo, execute o comando:

```sh
python "10KK VIEW.py"
```

### 💻 **Gerar um .exe (Opcional)**
Caso prefira criar um executavél, utilize o PyInstaller:

```sh
pip install pyinstaller
pyinstaller --onefile --noconsole --icon="icone_agente.ico" --hidden-import win32service "10KK VIEW.py"
```
