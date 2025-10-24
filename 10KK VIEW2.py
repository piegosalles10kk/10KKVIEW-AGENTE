import psutil
import json
import time
import logging
import platform
import os
import datetime
import sys
import random 
import subprocess
from typing import Optional, Dict, Any, List
import threading
from collections import deque

# Import NVML components for NVIDIA GPU monitoring
try:
    from pynvml import *
    has_pynvml = True
except (ImportError, Exception):
    has_pynvml = False

# Importar `msvcrt` apenas se for Windows para bloqueio de arquivo
if platform.system() == "Windows":
    import msvcrt
else:
    msvcrt = None

try:
    import wmi
    has_wmi = True
except ImportError:
    wmi = None
    has_wmi = False

# --- Variáveis Globais de Configuração ---
SHARED_NETWORK_PATH = ""
COLLECTION_INTERVAL_SECONDS = 10
MACHINE_ALIAS = ""

# --- Configurações de Retry ---
MAX_RETRIES = 3  # Reduzido de 5 para 3 para respostas mais rápidas
INITIAL_BACKOFF_SECONDS = 0.5  # Reduzido de 1 para 0.5
MAX_BACKOFF_SECONDS = 30  # Reduzido de 60 para 30

# Cache para otimizar chamadas repetidas
_cache = {
    'cpu_name': None,
    'wmi_connection': None,
    'gpu_info_static': None,
    'last_cache_time': 0
}
CACHE_DURATION_SECONDS = 300  # 5 minutos

# --- Obter o caminho do executável para logs e config.json ---
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.dirname(os.path.abspath(__file__))

# --- Configuração de Logging Otimizada ---
log_file_path = os.path.join(application_path, 'monitor_agent_script.log')

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

if logger.hasHandlers():
    logger.handlers.clear()

console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.WARNING)
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

# Handler de arquivo com rotação para não crescer indefinidamente
from logging.handlers import RotatingFileHandler
file_handler = RotatingFileHandler(
    log_file_path, 
    mode='a', 
    maxBytes=5*1024*1024,  # 5MB
    backupCount=3,
    encoding='utf-8'
)
file_handler.setLevel(logging.INFO)
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Log initial warnings for optional modules
if not has_pynvml:
    logger.warning("pynvml não encontrada. O monitoramento de GPU NVIDIA não estará disponível.")
if not has_wmi and platform.system() == "Windows":
    logger.warning("Módulo 'wmi' não encontrado. Monitoramento detalhado de hardware do Windows (via OpenHardwareMonitor) pode ser limitado.")

# --- Função para carregar configurações ---
def load_configuration(config_file_name="config.json") -> Dict[str, Any]:
    global SHARED_NETWORK_PATH, COLLECTION_INTERVAL_SECONDS, MACHINE_ALIAS

    config_path = os.path.join(application_path, config_file_name)
    default_config = {
        "SHARED_NETWORK_PATH": r"\\10.10.10.61\ti\SIA",
        "COLLECTION_INTERVAL_SECONDS": 10,
        "MACHINE_ALIAS": "",
        "LOCAL": True,
        "API": False,
        "APIURL": ""
    }

    if not os.path.exists(config_path):
        logger.warning(f"Arquivo de configuração '{config_path}' não encontrado. Criando um arquivo padrão.")
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Arquivo de configuração padrão criado em: {config_path}")
        except Exception as e:
            logger.error(f"Erro ao criar arquivo de configuração padrão: {e}")
        
        SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
        COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
        MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
        return default_config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        SHARED_NETWORK_PATH = config.get("SHARED_NETWORK_PATH", default_config["SHARED_NETWORK_PATH"])
        COLLECTION_INTERVAL_SECONDS = config.get("COLLECTION_INTERVAL_SECONDS", default_config["COLLECTION_INTERVAL_SECONDS"])
        MACHINE_ALIAS = config.get("MACHINE_ALIAS", default_config["MACHINE_ALIAS"])
        
        # Garantir que as chaves API existam
        config.setdefault("LOCAL", True)
        config.setdefault("API", False)
        config.setdefault("APIURL", "")
        
        logger.info(f"Configurações carregadas de '{config_path}'. Caminho de rede: {SHARED_NETWORK_PATH}, Intervalo: {COLLECTION_INTERVAL_SECONDS}s, Apelido da Máquina: '{MACHINE_ALIAS}'")
        return config
    except json.JSONDecodeError:
        logger.error(f"Erro ao decodificar JSON do arquivo de configuração '{config_path}'. Usando valores padrão.")
    except Exception as e:
        logger.error(f"Erro inesperado ao carregar arquivo de configuração '{config_path}': {e}. Usando valores padrão.")
    
    SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
    COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
    MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
    return default_config

# --- Cache WMI Connection ---
def get_wmi_connection():
    """Obtém conexão WMI em cache para melhor performance"""
    global _cache
    
    if _cache['wmi_connection'] is not None:
        return _cache['wmi_connection']
    
    if not has_wmi or platform.system() != "Windows":
        return None
    
    try:
        _cache['wmi_connection'] = wmi.WMI(namespace="root\\OpenHardwareMonitor")
        return _cache['wmi_connection']
    except Exception as e:
        logger.warning(f"Não foi possível conectar ao WMI OpenHardwareMonitor: {e}")
        return None

# --- Funções de Coleta de Hardware Otimizadas ---

def get_cpu_info() -> Dict[str, Any]:
    """Coleta informações de CPU de forma otimizada"""
    # Usar interval=None para leitura instantânea (mais rápido)
    cpu_percent = psutil.cpu_percent(interval=0.1)  # Intervalo mínimo para precisão
    cpu_cores_physical = psutil.cpu_count(logical=False)
    cpu_cores_logical = psutil.cpu_count(logical=True)
    
    # Cache do nome do processador
    if _cache['cpu_name'] is None:
        _cache['cpu_name'] = platform.processor()
    
    cpu_freq = psutil.cpu_freq()

    cpu_info = {
        "percentual_uso": round(cpu_percent, 2),
        "nucleos_fisicos": cpu_cores_physical,
        "nucleos_logicos": cpu_cores_logical,
        "frequencia_mhz": round(cpu_freq.current, 2) if cpu_freq else None,
        "nome": _cache['cpu_name'],
        "temperatura_package_celsius": None,
        "temperaturas_cores_celsius": {},
        "uso_total_percent": None,
        "energia_watts": None,
        "clocks_mhz": None
    }

    # Tentar obter informações adicionais via WMI (se disponível)
    if platform.system() == "Windows":
        wmi_conn = get_wmi_connection()
        if wmi_conn:
            try:
                hardware_info = wmi_conn.Hardware()
                for hw in hardware_info:
                    if hw.HardwareType.lower() == "cpu":
                        cpu_info['nome'] = hw.Name
                        sensors_wmi = wmi_conn.Sensor(Parent=hw.Identifier)
                        temp_sensors_data = {}
                        
                        for sensor in sensors_wmi:
                            sensor_type = sensor.SensorType.lower()
                            sensor_name_key = sensor.Name.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").replace("#", "").lower()
                            
                            if sensor_type not in temp_sensors_data:
                                temp_sensors_data[sensor_type] = {}
                            temp_sensors_data[sensor_type][sensor_name_key] = round(sensor.Value, 2)

                        if 'temperature' in temp_sensors_data:
                            for key, value in temp_sensors_data['temperature'].items():
                                if 'package' in key or 'cpu' in key:
                                    cpu_info['temperatura_package_celsius'] = value
                                elif 'core' in key:
                                    cpu_info['temperaturas_cores_celsius'][key] = value
                        
                        if 'load' in temp_sensors_data:
                            cpu_info['uso_total_percent'] = temp_sensors_data['load'].get('cpu_total', cpu_percent)
                        
                        if 'power' in temp_sensors_data:
                            cpu_info['energia_watts'] = temp_sensors_data['power'].get('cpu_package', None)
                        
                        if 'clock' in temp_sensors_data:
                            cpu_info['clocks_mhz'] = temp_sensors_data['clock']
                        break
            except Exception as e:
                logger.debug(f"Erro ao obter informações detalhadas da CPU via WMI: {e}")

    return cpu_info


def get_memory_info() -> Dict[str, Any]:
    """Coleta informações de memória RAM"""
    mem = psutil.virtual_memory()
    swap = psutil.swap_memory()

    return {
        "total_gb": round(mem.total / (1024**3), 2),
        "usado_gb": round(mem.used / (1024**3), 2),
        "livre_gb": round(mem.available / (1024**3), 2),
        "percentual_uso": round(mem.percent, 2),
        "swap_total_gb": round(swap.total / (1024**3), 2),
        "swap_usado_gb": round(swap.used / (1024**3), 2),
        "swap_percentual_uso": round(swap.percent, 2)
    }


def get_disk_info() -> List[Dict[str, Any]]:
    """Coleta informações de disco de forma otimizada"""
    disks = []
    
    # Obter todas as partições de uma vez
    partitions = psutil.disk_partitions(all=False)
    
    for partition in partitions:
        # Ignorar partições de sistema no Windows
        if platform.system() == "Windows":
            if 'cdrom' in partition.opts or partition.fstype == '':
                continue
        
        try:
            usage = psutil.disk_usage(partition.mountpoint)
            disks.append({
                "dispositivo": partition.device,
                "ponto_montagem": partition.mountpoint,
                "tipo": partition.fstype,
                "total_gb": round(usage.total / (1024**3), 2),
                "usado_gb": round(usage.used / (1024**3), 2),
                "livre_gb": round(usage.free / (1024**3), 2),
                "percentual_uso": round(usage.percent, 2)
            })
        except (PermissionError, OSError) as e:
            logger.debug(f"Não foi possível acessar {partition.mountpoint}: {e}")
            continue

    return disks


def get_network_info() -> Dict[str, Any]:
    """Coleta informações de rede de forma otimizada"""
    net_io = psutil.net_io_counters()
    
    network_info = {
        "bytes_enviados": net_io.bytes_sent,
        "bytes_recebidos": net_io.bytes_recv,
        "pacotes_enviados": net_io.packets_sent,
        "pacotes_recebidos": net_io.packets_recv,
        "erros_entrada": net_io.errin,
        "erros_saida": net_io.errout,
        "interfaces": {}
    }

    # Coletar informações por interface de forma mais eficiente
    try:
        net_if_stats = psutil.net_if_stats()
        net_if_addrs = psutil.net_if_addrs()
        
        for interface_name, stats in net_if_stats.items():
            if stats.isup:  # Apenas interfaces ativas
                network_info["interfaces"][interface_name] = {
                    "velocidade_mbps": stats.speed if stats.speed > 0 else None,
                    "status": "up" if stats.isup else "down",
                    "enderecos": []
                }
                
                # Adicionar endereços IP se disponíveis
                if interface_name in net_if_addrs:
                    for addr in net_if_addrs[interface_name]:
                        if addr.family == 2:  # AF_INET (IPv4)
                            network_info["interfaces"][interface_name]["enderecos"].append({
                                "tipo": "IPv4",
                                "endereco": addr.address
                            })
    except Exception as e:
        logger.debug(f"Erro ao coletar informações de interfaces de rede: {e}")

    return network_info


def get_gpu_info() -> List[Dict[str, Any]]:
    """Coleta informações de GPU de forma otimizada"""
    gpus = []

    if has_pynvml:
        try:
            nvmlInit()
            device_count = nvmlDeviceGetCount()
            
            for i in range(device_count):
                handle = nvmlDeviceGetHandleByIndex(i)
                
                # Informações estáticas em cache
                cache_key = f'gpu_{i}_static'
                current_time = time.time()
                
                if cache_key not in _cache or (current_time - _cache['last_cache_time']) > CACHE_DURATION_SECONDS:
                    gpu_name = nvmlDeviceGetName(handle)
                    if isinstance(gpu_name, bytes):
                        gpu_name = gpu_name.decode('utf-8')
                    
                    memory_info = nvmlDeviceGetMemoryInfo(handle)
                    _cache[cache_key] = {
                        'name': gpu_name,
                        'memory_total': memory_info.total
                    }
                    _cache['last_cache_time'] = current_time
                else:
                    memory_info = nvmlDeviceGetMemoryInfo(handle)

                static_info = _cache[cache_key]
                
                # Informações dinâmicas
                utilization = nvmlDeviceGetUtilizationRates(handle)
                temperature = nvmlDeviceGetTemperature(handle, NVML_TEMPERATURE_GPU)
                power_usage = nvmlDeviceGetPowerUsage(handle) / 1000.0  # mW to W
                
                gpus.append({
                    "nome": static_info['name'],
                    "memoria_total_mb": round(static_info['memory_total'] / (1024**2), 2),
                    "memoria_usada_mb": round(memory_info.used / (1024**2), 2),
                    "memoria_livre_mb": round(memory_info.free / (1024**2), 2),
                    "percentual_uso_gpu": utilization.gpu,
                    "percentual_uso_memoria": utilization.memory,
                    "temperatura_celsius": temperature,
                    "energia_watts": round(power_usage, 2)
                })
                
        except NVMLError as error:
            logger.warning(f"Erro ao acessar GPU NVIDIA via NVML: {error}")
        finally:
            try:
                nvmlShutdown()
            except:
                pass

    return gpus


def get_system_info() -> Dict[str, Any]:
    """Coleta informações gerais do sistema"""
    boot_time = psutil.boot_time()
    uptime_seconds = time.time() - boot_time
    
    # Detectar versão do Windows com mais precisão
    os_version = platform.version()
    os_release = platform.release()
    
    # Identificar Windows 10 vs 11
    windows_version = "Unknown"
    if platform.system() == "Windows":
        try:
            # Windows 11 tem build >= 22000
            build_number = int(platform.version().split('.')[-1])
            if build_number >= 22000:
                windows_version = "Windows 11"
            else:
                windows_version = "Windows 10"
        except:
            windows_version = f"Windows {os_release}"

    return {
        "hostname": platform.node(),
        "sistema_operacional": f"{platform.system()} {windows_version}",
        "versao_so": os_version,
        "arquitetura": platform.machine(),
        "tempo_ligado_horas": round(uptime_seconds / 3600, 2),
        "timestamp": datetime.datetime.now().isoformat()
    }


def collect_all_data() -> Optional[Dict[str, Any]]:
    """Coleta todos os dados de hardware de forma otimizada"""
    try:
        system_info = get_system_info()
        
        # Coletar dados em paralelo quando possível
        data = {
            "machine_alias": MACHINE_ALIAS if MACHINE_ALIAS else system_info["hostname"],
            "hostname": system_info["hostname"],
            "sistema_operacional": system_info["sistema_operacional"],
            "versao_so": system_info["versao_so"],
            "arquitetura": system_info["arquitetura"],
            "tempo_ligado_horas": system_info["tempo_ligado_horas"],
            "timestamp": system_info["timestamp"],
            "cpu": get_cpu_info(),
            "memoria": get_memory_info(),
            "discos": get_disk_info(),
            "rede": get_network_info(),
            "gpus": get_gpu_info()
        }

        return data
    except Exception as e:
        logger.error(f"Erro ao coletar dados de hardware: {e}", exc_info=True)
        return None


# --- Funções de Bloqueio de Arquivo Otimizadas ---

def acquire_file_lock(file_path: str, timeout_seconds: float = 5) -> Optional[int]:
    """
    Tenta adquirir um bloqueio exclusivo em um arquivo.
    Retorna o descritor de arquivo se bem-sucedido, None caso contrário.
    Otimizado para Windows 10/11.
    """
    if platform.system() != "Windows" or msvcrt is None:
        return None

    lock_file_path = file_path + ".lock"
    start_time = time.time()
    
    while (time.time() - start_time) < timeout_seconds:
        try:
            # Criar arquivo de lock com flag exclusiva
            lock_fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
            
            try:
                # Tentar bloquear o arquivo
                msvcrt.locking(lock_fd, msvcrt.LK_NBLCK, 1)
                logger.debug(f"Bloqueio adquirido para '{lock_file_path}'")
                return lock_fd
            except IOError:
                os.close(lock_fd)
                if os.path.exists(lock_file_path):
                    try:
                        os.remove(lock_file_path)
                    except:
                        pass
                
        except FileExistsError:
            # Arquivo de lock já existe, verificar se está obsoleto
            try:
                if os.path.exists(lock_file_path):
                    lock_age = time.time() - os.path.getmtime(lock_file_path)
                    if lock_age > 60:  # Lock obsoleto (>1 minuto)
                        logger.warning(f"Removendo lock obsoleto: {lock_file_path}")
                        try:
                            os.remove(lock_file_path)
                        except:
                            pass
            except:
                pass
        
        time.sleep(0.05)  # Pequeno delay antes de tentar novamente
    
    logger.warning(f"Timeout ao tentar adquirir bloqueio para '{lock_file_path}'")
    return None


def release_file_lock(lock_fd: Optional[int], lock_file_path: str):
    """Libera o bloqueio de arquivo"""
    if lock_fd is None:
        return
    
    if platform.system() == "Windows" and msvcrt is not None:
        try:
            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1)
            os.close(lock_fd)
            
            if os.path.exists(lock_file_path):
                try:
                    os.remove(lock_file_path)
                except:
                    pass
            
            logger.debug(f"Bloqueio liberado: {lock_file_path}")
        except Exception as e:
            logger.error(f"Erro ao liberar bloqueio para '{lock_file_path}': {e}")


# --- Função de Escrita Otimizada ---

def write_data_to_files(data: Dict[str, Any], base_path: str, config: Dict[str, Any]) -> bool:
    """
    Escreve os dados coletados de forma otimizada com retry e fallback.
    """
    if not data:
        logger.error("Dados vazios para escrita. Não será salvo.")
        return False

    current_date = datetime.datetime.now()
    month_folder = current_date.strftime("%Y-%m")
    monthly_path = os.path.join(base_path, month_folder)

    try:
        os.makedirs(monthly_path, exist_ok=True)
        logger.debug(f"Pasta mensal '{monthly_path}' verificada/criada.")
    except OSError as e:
        logger.error(f"Erro ao criar/verificar pasta mensal '{monthly_path}': {e}")
        return False

    file_identifier = data.get('machine_alias', data['hostname'])
    individual_path = os.path.join(monthly_path, f"{file_identifier}.json")
    general_path = os.path.join(monthly_path, "dados_gerais_mensal.json")

    def _write_json_with_retries(file_full_path: str, data_to_append: Dict[str, Any], is_general_json: bool = False) -> bool:
        """Função interna para escrever JSON com retry"""
        current_backoff = INITIAL_BACKOFF_SECONDS
        lock_fd = None
        
        for attempt in range(MAX_RETRIES):
            try:
                lock_fd = acquire_file_lock(file_full_path, timeout_seconds=current_backoff + 2)
                if lock_fd is None:
                    raise Exception("Não foi possível adquirir o bloqueio de arquivo.")

                content_list = []

                # Ler arquivo existente
                if os.path.exists(file_full_path) and os.path.getsize(file_full_path) > 0:
                    try:
                        with open(file_full_path, 'r', encoding='utf-8') as f_read:
                            content_list = json.load(f_read)
                            
                            if not isinstance(content_list, list):
                                logger.warning(f"Conteúdo não é lista, recriando arquivo: {file_full_path}")
                                content_list = []
                    except json.JSONDecodeError:
                        logger.warning(f"JSON corrompido, recriando arquivo: {file_full_path}")
                        content_list = []

                content_list.append(data_to_append)

                # Escrever de volta
                with open(file_full_path, 'w', encoding='utf-8') as f_write:
                    json.dump(content_list, f_write, indent=2, ensure_ascii=False)  # indent=2 em vez de 4 para economizar espaço

                logger.info(f"✅ JSON {'geral' if is_general_json else 'individual'} atualizado: {os.path.basename(file_full_path)}")
                return True

            except Exception as e:
                if attempt == MAX_RETRIES - 1:
                    logger.error(f"❌ Falha ao escrever {file_full_path} após {MAX_RETRIES} tentativas: {e}")
                else:
                    logger.warning(f"Tentativa {attempt + 1}/{MAX_RETRIES} falhou para {file_full_path}: {e}")
            
            finally:
                if lock_fd:
                    release_file_lock(lock_fd, file_full_path + ".lock")
                    lock_fd = None

            sleep_time = min(current_backoff + random.uniform(0, 0.1), MAX_BACKOFF_SECONDS)
            time.sleep(sleep_time)
            current_backoff *= 2

        return False

    success = False
    
    # Tentar API primeiro se configurado
    if config.get("API", False) and config.get("APIURL"):
        try:
            import requests
            response = requests.post(
                config["APIURL"],
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=5  # Timeout reduzido para 5 segundos
            )
            if response.status_code == 201:
                logger.info(f"📤 Dados enviados para API: {config['APIURL']}")
                success = True
                
                # Se LOCAL está desativado e API funcionou, não gravar local
                if not config.get("LOCAL", True):
                    return True
            else:
                logger.warning(f"❌ API retornou status {response.status_code}")
        except Exception as e:
            logger.error(f"❌ Erro ao enviar para API: {e}")

    # Gravar localmente se necessário
    if config.get("LOCAL", True) or not success:
        success_individual = _write_json_with_retries(individual_path, data, is_general_json=False)
        success_general = _write_json_with_retries(general_path, data, is_general_json=True)
        success = success_individual or success_general

    return success


# --- Execução Principal ---
if __name__ == '__main__':
    # Configuração inicial
    config = load_configuration()
    if not config:
        logger.error("Falha ao carregar a configuração inicial. Encerrando.")
        sys.exit(1)

    logger.info("=" * 60)
    logger.info("🚀 Agente de Monitoramento Otimizado - Iniciado")
    logger.info(f"💾 Caminho de salvamento: {os.path.abspath(SHARED_NETWORK_PATH)}")
    logger.info(f"⏱️  Intervalo de coleta: {COLLECTION_INTERVAL_SECONDS}s")
    logger.info(f"🖥️  Sistema: {platform.system()} {platform.release()}")
    logger.info(f"🏷️  Apelido da máquina: {MACHINE_ALIAS if MACHINE_ALIAS else 'Não definido'}")
    logger.info("=" * 60)

    # Loop principal
    collection_count = 0
    while True:
        try:
            start_time = time.time()
            
            collected_data = collect_all_data()
            
            if collected_data:
                if write_data_to_files(collected_data, SHARED_NETWORK_PATH, config):
                    collection_count += 1
                    elapsed = time.time() - start_time
                    logger.info(f"📊 Coleta #{collection_count} concluída em {elapsed:.2f}s | Próxima em {COLLECTION_INTERVAL_SECONDS}s")
                else:
                    logger.error("❌ Erro ao salvar dados coletados.")
            else:
                logger.error("❌ Não foi possível coletar dados de hardware.")

            time.sleep(COLLECTION_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("\n" + "=" * 60)
            logger.info("⏹️  Monitoramento interrompido pelo usuário (Ctrl+C)")
            logger.info(f"📊 Total de coletas realizadas: {collection_count}")
            logger.info("=" * 60)
            break
            
        except Exception as e:
            logger.critical(f"❌ Erro crítico no loop principal: {e}", exc_info=True)
            logger.info(f"🔄 Tentando novamente em {COLLECTION_INTERVAL_SECONDS} segundos...")
            time.sleep(COLLECTION_INTERVAL_SECONDS)