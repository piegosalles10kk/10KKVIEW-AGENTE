import psutil
import json
import time
import logging
import platform
import os
import datetime
import sys
import random 

# Importar `msvcrt` apenas se for Windows
if platform.system() == "Windows":
    import msvcrt
    MSVCRT_LK_UNLCK = 0  # Release lock
    MSVCRT_LK_LOCK = 1   # Lock for exclusive use
    MSVCRT_LK_NBLCK = 4  # Non-blocking lock for writing - this is usually the one you want for polling
else:
    msvcrt = None
    logging.warning("msvcrt não está disponível (não é Windows). O bloqueio de arquivo simples não funcionará de forma confiável.")

try:
    import wmi
except ImportError:
    wmi = None

# --- Variáveis Globais de Configuração ---
SHARED_NETWORK_PATH = ""
COLLECTION_INTERVAL_SECONDS = 10
MACHINE_ALIAS = ""

# --- Configurações de Retry ---
MAX_RETRIES = 5  
INITIAL_BACKOFF_SECONDS = 1 
MAX_BACKOFF_SECONDS = 60 

# --- Obter o caminho do executável para logs e config.json ---
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# --- Configuração de Logging ---
log_file_path = os.path.join(application_path, 'monitor_agent_script.log')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8', delay=True)
file_handler.setLevel(logging.ERROR)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

logging.root = logger 

# --- Função para carregar configurações ---
def load_configuration(config_file_name="config.json"):
    global SHARED_NETWORK_PATH, COLLECTION_INTERVAL_SECONDS, MACHINE_ALIAS
    
    config_path = os.path.join(application_path, config_file_name)

    if not os.path.exists(config_path):
        logging.warning(f"Arquivo de configuração '{config_path}' não encontrado. Criando um arquivo padrão.")
        default_config = {
            "SHARED_NETWORK_PATH": r"\\10.10.10.61\ti\SIA",
            "COLLECTION_INTERVAL_SECONDS": 10,
            "MACHINE_ALIAS": ""
        }
        try:
            with open(config_path, 'w') as f:
                json.dump(default_config, f, indent=4)
            logging.info(f"Arquivo de configuração padrão criado em: {config_path}")
        except Exception as e:
            logging.error(f"Erro ao criar arquivo de configuração padrão: {e}")
            SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
            COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
            MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
            return False 

    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        
        SHARED_NETWORK_PATH = config.get("SHARED_NETWORK_PATH", r"\\10.10.10.61\ti\SIA")
        COLLECTION_INTERVAL_SECONDS = config.get("COLLECTION_INTERVAL_SECONDS", 10)
        MACHINE_ALIAS = config.get("MACHINE_ALIAS", "")
        
        logging.info(f"Configurações carregadas de '{config_path}'. Caminho de rede: {SHARED_NETWORK_PATH}, Intervalo: {COLLECTION_INTERVAL_SECONDS}s, Apelido da Máquina: '{MACHINE_ALIAS}'")
        return True 
    except json.JSONDecodeError:
        logging.error(f"Erro ao decodificar JSON do arquivo de configuração '{config_path}'. Verifique o formato. Usando valores padrão.")
        SHARED_NETWORK_PATH = r"\\10.10.10.61\ti\SIA"
        COLLECTION_INTERVAL_SECONDS = 10
        MACHINE_ALIAS = ""
        return False
    except Exception as e:
        logging.error(f"Erro inesperado ao carregar arquivo de configuração '{config_path}': {e}. Usando valores padrão.")
        SHARED_NETWORK_PATH = r"\\10.10.10.61\ti\SIA"
        COLLECTION_INTERVAL_SECONDS = 10
        MACHINE_ALIAS = ""
        return False

def get_hardware_data():
    """Coleta os dados de hardware e sistema e os consolida em um único objeto."""
    
    final_data = {}
    monitoramento_data = {
        "cpu": {}, "memoria_ram": {}, "disco_principal": {},
        "discos_adicionais": [], "gpu": {}, "rede": {},
        "placa_mae": {}, "uptime_horas": None
    }

    try:
        cpu_percent = psutil.cpu_percent(interval=None) 
        mem = psutil.virtual_memory()
        main_disk_path = 'C:\\' if platform.system() == "Windows" else '/'
        disk_usage_main = psutil.disk_usage(main_disk_path)
        
        net_io_before = psutil.net_io_counters()
        time.sleep(1) 
        net_io_after = psutil.net_io_counters()

        bytes_sent_diff = net_io_after.bytes_sent - net_io_before.bytes_sent
        bytes_recv_diff = net_io_after.bytes_recv - net_io_before.bytes_recv 
        network_speed_mbps = round((bytes_sent_diff + bytes_recv_diff) * 8 / 1_000_000, 2) 

        monitoramento_data['cpu']['percentual_uso'] = cpu_percent
        monitoramento_data['cpu']['nucleos_fisicos'] = psutil.cpu_count(logical=False)
        monitoramento_data['cpu']['nucleos_logicos'] = psutil.cpu_count(logical=True)
        monitoramento_data['memoria_ram']['total_gb'] = round(mem.total / (1024**3), 2)
        monitoramento_data['memoria_ram']['usado_gb'] = round(mem.used / (1024**3), 2)
        monitoramento_data['memoria_ram']['percentual_uso'] = mem.percent
        monitoramento_data['disco_principal']['total_gb'] = round(disk_usage_main.total / (1024**3), 2)
        monitoramento_data['disco_principal']['usado_gb'] = round(disk_usage_main.used / (1024**3), 2)
        monitoramento_data['disco_principal']['livre_gb'] = round(disk_usage_main.free / (1024**3), 2)
        monitoramento_data['disco_principal']['percentual_uso'] = disk_usage_main.percent
        monitoramento_data['rede']['bytes_enviados_mb'] = round(net_io_after.bytes_sent / (1024**2), 2)
        monitoramento_data['rede']['bytes_recebidos_mb'] = round(net_io_after.bytes_recv / (1024**2), 2)
        monitoramento_data['rede']['velocidade_atual_mbps'] = network_speed_mbps
        monitoramento_data['uptime_horas'] = round((time.time() - psutil.boot_time()) / 3600, 2)
        
        final_data['hostname'] = platform.node()
        final_data['machine_alias'] = MACHINE_ALIAS if MACHINE_ALIAS else final_data['hostname']
        final_data['timestamp_coleta'] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        final_data['monitoramento'] = monitoramento_data

        if platform.system() == "Windows" and wmi is not None:
            try:
                c = wmi.WMI(namespace="root\\OpenHardwareMonitor")
                hardware_info = c.Hardware()
                
                cpu_processed = False
                gpu_processed = False
                main_disk_processed = False
                mainboard_processed = False

                for hw in hardware_info:
                    component_type = hw.HardwareType.lower()
                    component_name = hw.Name
                    
                    temp_sensors_data = {}
                    sensors_wmi = c.Sensor(Parent=hw.Identifier)
                    
                    for sensor in sensors_wmi:
                        sensor_type = sensor.SensorType.lower()
                        sensor_name_key = sensor.Name.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").replace("#", "").lower()
                        
                        if sensor_type not in temp_sensors_data:
                            temp_sensors_data[sensor_type] = {}
                        temp_sensors_data[sensor_type][sensor_name_key] = round(sensor.Value, 2)
                    
                    if component_type == "cpu" and not cpu_processed:
                        monitoramento_data['cpu']['nome'] = component_name
                        if 'temperature' in temp_sensors_data:
                            if 'cpu_package' in temp_sensors_data['temperature']:
                                monitoramento_data['cpu']['temperatura_package_celsius'] = temp_sensors_data['temperature']['cpu_package']
                            core_temps = {}
                            for k, v in temp_sensors_data['temperature'].items():
                                if 'cpu_core' in k:
                                    core_temps[k] = v
                            if core_temps:
                                monitoramento_data['cpu']['temperaturas_cores_celsius'] = core_temps
                        if 'load' in temp_sensors_data:
                             monitoramento_data['cpu']['uso_total_percent'] = temp_sensors_data['load'].get('cpu_total')
                        if 'power' in temp_sensors_data:
                            monitoramento_data['cpu']['energia_watts'] = temp_sensors_data['power']
                        if 'clock' in temp_sensors_data:
                            monitoramento_data['cpu']['clocks_mhz'] = temp_sensors_data['clock']
                        cpu_processed = True
                    elif "gpu" in component_type and not gpu_processed:
                        monitoramento_data['gpu']['nome'] = component_name
                        monitoramento_data['gpu']['tipo'] = hw.HardwareType
                        if 'temperature' in temp_sensors_data and 'gpu_core' in temp_sensors_data['temperature']:
                            monitoramento_data['gpu']['temperatura_core_celsius'] = temp_sensors_data['temperature']['gpu_core']
                        if 'load' in temp_sensors_data and 'gpu_core' in temp_sensors_data['load']:
                            monitoramento_data['gpu']['uso_percentual'] = temp_sensors_data['load']['gpu_core']
                        if 'smalldata' in temp_sensors_data: 
                            monitoramento_data['gpu']['memoria_gpu'] = {
                                "usada_mb": temp_sensors_data['smalldata'].get('gpu_memory_used'),
                                "livre_mb": temp_sensors_data['smalldata'].get('gpu_memory_free'),
                                "total_mb": temp_sensors_data['smalldata'].get('gpu_memory_total')
                            }
                        if 'clock' in temp_sensors_data:
                            monitoramento_data['gpu']['clocks_mhz'] = temp_sensors_data['clock']
                        gpu_processed = True
                    elif component_type == "hdd":
                        disk_entry = {
                            "nome": component_name,
                            "tipo": hw.HardwareType
                        }
                        if 'temperature' in temp_sensors_data and 'temperature' in temp_sensors_data['temperature']:
                            disk_entry['temperatura_celsius'] = temp_sensors_data['temperature']['temperature']
                            if not main_disk_processed and (main_disk_path in component_name or "ssd" in component_name.lower()): 
                                monitoramento_data['disco_principal']['nome'] = component_name
                                monitoramento_data['disco_principal']['temperatura_celsius'] = disk_entry['temperatura_celsius']
                                main_disk_processed = True
                        if 'load' in temp_sensors_data and 'used_space' in temp_sensors_data['load']:
                            disk_entry['uso_espaco_percent'] = temp_sensors_data['load']['used_space']
                            if not main_disk_processed and (main_disk_path in component_name or "ssd" in component_name.lower()):
                                monitoramento_data['disco_principal']['uso_espaco_percent'] = disk_entry['uso_espaco_percent']
                                main_disk_processed = True
                        if 'level' in temp_sensors_data and 'remaining_life' in temp_sensors_data['level']:
                            disk_entry['vida_util_restante_percent'] = temp_sensors_data['level']['remaining_life']
                            if not main_disk_processed and (main_disk_path in component_name or "ssd" in component_name.lower()):
                                monitoramento_data['disco_principal']['vida_util_restante_percent'] = disk_entry['vida_util_restante_percent']
                                main_disk_processed = True
                        if 'data' in temp_sensors_data and 'total_bytes_written' in temp_sensors_data['data']:
                            disk_entry['dados_gravados_tb'] = round(temp_sensors_data['data']['total_bytes_written'] / (1024**4), 2)
                        if not main_disk_processed or monitoramento_data['disco_principal'].get('nome') != component_name:
                            monitoramento_data['discos_adicionais'].append(disk_entry)
                    elif component_type == "mainboard" and not mainboard_processed:
                        monitoramento_data['placa_mae']['nome'] = component_name
                        if 'temperature' in temp_sensors_data:
                            monitoramento_data['placa_mae']['temperaturas_celsius'] = temp_sensors_data['temperature']
                        mainboard_processed = True
                
                logging.info("Dados detalhados do Open Hardware Monitor coletados com sucesso.")

            except wmi.x_wmi as e:
                logging.error(f"Erro WMI ao obter dados do Open Hardware Monitor. Verifique se o OHM está rodando e o namespace está acessível: {e}")
            except Exception as e:
                logging.error(f"Erro inesperado ao tentar obter dados detalhados via Open Hardware Monitor: {e}")
        
        elif platform.system() == "Linux" and hasattr(psutil, "sensors_temperatures"):
            temps = psutil.sensors_temperatures()
            if temps:
                cpu_temp = temps.get('coretemp') or temps.get('cpu_thermal')
                if cpu_temp:
                    monitoramento_data['cpu']['nome'] = "CPU (Linux)"
                    monitoramento_data['cpu']['temperatura_package_celsius'] = cpu_temp[0].current if cpu_temp else None
                    core_temps = {}
                    for i, entry in enumerate(cpu_temp):
                        if 'current' in entry._fields:
                            core_temps[f"core_{entry.label or i+1}"] = entry.current
                    monitoramento_data['cpu']['temperaturas_cores_celsius'] = core_temps
                logging.info("Temperaturas básicas da CPU coletadas via psutil (Linux).")
            else:
                logging.info("Linux: psutil.sensors_temperatures() retornou vazio ou não é suportado.")
        else:
            logging.info("Coleta detalhada de hardware (via Open Hardware Monitor) não suportada neste SO ou módulo WMI não disponível.")

    except Exception as e:
        logging.error(f"Erro geral ao coletar dados de hardware: {e}")
        return None
    
    return final_data

def acquire_file_lock(file_path, timeout_seconds=10, check_interval_seconds=0.1):
    """
    Tenta adquirir um bloqueio de arquivo simples criando/acessando um arquivo .lock.
    Retorna o caminho para o arquivo de lock se o bloqueio for adquirido, None caso contrário.
    """
    if msvcrt is None:
        logging.error("msvcrt não está disponível, bloqueio de arquivo não suportado neste SO.")
        return None

    lock_file_path = file_path + ".lock"
    start_time = time.time()

    while time.time() - start_time < timeout_seconds:
        try:
            # Tenta abrir o arquivo de lock em modo exclusivo (x)
            # Se já existir e estiver bloqueado, vai falhar (FileExistsError)
            fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            # Tenta bloquear o arquivo
            msvcrt.locking(fd, MSVCRT_LK_LOCK, 1) # Bloqueia 1 byte do arquivo
            os.close(fd) # Fecha o descritor de arquivo, mas o bloqueio persiste no Windows
            logging.debug(f"Bloqueio adquirido para: {lock_file_path}")
            return lock_file_path
        except FileExistsError:
            logging.debug(f"Arquivo de lock '{lock_file_path}' já existe. Esperando...")
            time.sleep(check_interval_seconds)
        except PermissionError:
            logging.debug(f"Permissão negada ao tentar criar/acessar '{lock_file_path}'. Esperando...")
            time.sleep(check_interval_seconds)
        except Exception as e:
            logging.warning(f"Erro inesperado ao tentar adquirir bloqueio para '{lock_file_path}': {e}. Esperando...")
            time.sleep(check_interval_seconds)
    
    logging.error(f"Não foi possível adquirir bloqueio para '{file_path}' após {timeout_seconds} segundos.")
    return None

def release_file_lock(lock_file_path):
    """Libera o bloqueio de arquivo removendo o arquivo .lock."""
    if msvcrt is None:
        return 
    try:
        if os.path.exists(lock_file_path):
            os.remove(lock_file_path)
            logging.debug(f"Bloqueio liberado para: {lock_file_path}")
    except Exception as e:
        logging.error(f"Erro ao liberar bloqueio para '{lock_file_path}': {e}")


def write_data_to_files(data, base_path):
    """
    Escreve os dados coletados em:
    1. Acumula os dados em um JSON individual da máquina.
    2. Adiciona uma entrada ao JSON geral mensal (um único arquivo por mês).
    Implementa retries com backoff e um bloqueio de arquivo simples.
    """
    if not data:
        logging.error("Dados vazios para escrita. Não será salvo.")
        return False

    current_date = datetime.datetime.now()
    month_folder = current_date.strftime("%Y-%m")
    monthly_path = os.path.join(base_path, month_folder)

    if not os.path.exists(monthly_path):
        try:
            os.makedirs(monthly_path)
            logging.info(f"Pasta mensal '{monthly_path}' criada com sucesso.")
        except OSError as e:
            logging.error(f"Erro ao criar pasta mensal '{monthly_path}': {e}")
            return False

    file_identifier = data.get('machine_alias', data['hostname'])
    
    def _write_json_with_retries(file_full_path, data_to_append, is_general_json=False):
        current_backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            lock_path = None
            try:
                lock_path = acquire_file_lock(file_full_path, timeout_seconds=INITIAL_BACKOFF_SECONDS)
                if lock_path is None:
                    raise Exception("Não foi possível adquirir o bloqueio de arquivo.")

                content_list = []
                
                if os.path.exists(file_full_path):
                    with open(file_full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                        if content:
                            try:
                                content_list = json.loads(content)
                                if not isinstance(content_list, list):
                                    # Se não for uma lista, considera corrompido ou formato inesperado.
                                    # Não sobrescreve, apenas loga e falha esta tentativa para retry.
                                    raise ValueError(f"Conteúdo de JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' não é uma lista. Possivelmente corrompido ou formato inesperado.")
                            except json.JSONDecodeError as e:
                                # JSON está malformado. Loga e falha esta tentativa para retry.
                                raise json.JSONDecodeError(f"JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' corrompido: {e}", e.doc, e.pos)
                            except Exception as e:
                                # Outros erros inesperados na leitura. Loga e falha esta tentativa para retry.
                                raise Exception(f"Erro inesperado ao ler JSON {'geral' if is_general_json else 'individual'} '{file_full_path}': {e}")
                
                content_list.append(data_to_append) 
                
                # Escreve o JSON atualizado
                with open(file_full_path, 'w', encoding='utf-8') as f:
                    json.dump(content_list, f, indent=4)
                
                logging.info(f"JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' atualizado com sucesso na tentativa {attempt + 1}.")
                return True

            except (json.JSONDecodeError, ValueError, Exception) as e:
                # Capture os erros de JSONDecodeError, ValueError (formato) e outros erros
                # Aumente o nível do log para ERROR para esses casos, para indicar um problema
                # persistente que impede a escrita dos dados.
                log_message = f"Não foi possível processar JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' na tentativa {attempt + 1}/{MAX_RETRIES}: {e}. O arquivo existente NÃO será sobrescrito. Tentando novamente em {current_backoff:.2f} segundos."
                if attempt == MAX_RETRIES - 1: # Se for a última tentativa, loga como ERROR
                    logging.error(log_message)
                else:
                    logging.warning(log_message)
            finally:
                if lock_path:
                    release_file_lock(lock_path)
            
            sleep_time = current_backoff + random.uniform(0, current_backoff * 0.1) 
            time.sleep(min(sleep_time, MAX_BACKOFF_SECONDS))
            current_backoff *= 2 
            
        logging.error(f"Falha CRÍTICA ao atualizar JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' após {MAX_RETRIES} tentativas. Os dados não foram salvos e o arquivo original (corrompido ou não) foi mantido.")
        return False

    # --- Chamadas das funções auxiliares ---

    individual_full_path = os.path.join(monthly_path, f"{file_identifier}.json")
    if not _write_json_with_retries(individual_full_path, data, is_general_json=False):
        return False 

    general_full_path = os.path.join(monthly_path, "dados_gerais_mensal.json")
    return _write_json_with_retries(general_full_path, data, is_general_json=True)


# --- Execução principal do script ---
if __name__ == '__main__':
    load_configuration() 
    
    logging.info("Iniciando o agente de monitoramento em modo de script.")
    logging.info(f"Os dados serão salvos em: {os.path.abspath(SHARED_NETWORK_PATH)}")
    
    while True:
        data = get_hardware_data()
        if data:
            write_data_to_files(data, SHARED_NETWORK_PATH)
        else:
            logging.error("Não foi possível coletar dados de hardware. Verifique o log para detalhes.")
        
        logging.info(f"Próxima coleta em {COLLECTION_INTERVAL_SECONDS} segundos...")
        time.sleep(COLLECTION_INTERVAL_SECONDS)