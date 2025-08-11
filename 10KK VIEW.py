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

# Import NVML components for NVIDIA GPU monitoring
try:
    from pynvml import *
    has_pynvml = True
except ImportError:
    has_pynvml = False
    # Logging will be handled later, no direct print here
except NVMLError as error:
    has_pynvml = False
    # Logging will be handled later

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

# Configuração do logger para usar o módulo logging padrão
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO) # Nível padrão do logger

# Limpa handlers existentes para evitar duplicação em re-execuções/testes
if logger.hasHandlers():
    logger.handlers.clear()

console_handler = logging.StreamHandler(sys.stderr)
console_handler.setLevel(logging.WARNING) # Warnings e acima para o console
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

file_handler = logging.FileHandler(log_file_path, mode='a', encoding='utf-8') 
file_handler.setLevel(logging.INFO) # Tudo a partir de INFO para o arquivo de log
file_handler.setFormatter(formatter)
logger.addHandler(file_handler)

# Log initial warnings for optional modules
if not has_pynvml:
    logger.warning("pynvml não encontrada. O monitoramento de GPU NVIDIA não estará disponível.")
if not has_wmi and platform.system() == "Windows":
    logger.warning("Módulo 'wmi' não encontrado. Monitoramento detalhado de hardware do Windows (via OpenHardwareMonitor) pode ser limitado.")

# --- Função para carregar configurações ---
def load_configuration(config_file_name="config.json"):
    global SHARED_NETWORK_PATH, COLLECTION_INTERVAL_SECONDS, MACHINE_ALIAS

    config_path = os.path.join(application_path, config_file_name)

    if not os.path.exists(config_path):
        logger.warning(f"Arquivo de configuração '{config_path}' não encontrado. Criando um arquivo padrão.")
        default_config = {
            "SHARED_NETWORK_PATH": r"\\10.10.10.61\ti\SIA",
            "COLLECTION_INTERVAL_SECONDS": 10,
            "MACHINE_ALIAS": ""
        }
        try:
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(default_config, f, indent=4)
            logger.info(f"Arquivo de configuração padrão criado em: {config_path}")
            SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
            COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
            MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
            return default_config  # ← retorna o dict padrão
        except Exception as e:
            logger.error(f"Erro ao criar arquivo de configuração padrão: {e}")
            SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
            COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
            MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
            return default_config

    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        SHARED_NETWORK_PATH = config.get("SHARED_NETWORK_PATH", r"\\10.10.10.61\ti\SIA")
        COLLECTION_INTERVAL_SECONDS = config.get("COLLECTION_INTERVAL_SECONDS", 10)
        MACHINE_ALIAS = config.get("MACHINE_ALIAS", "")
        logger.info(f"Configurações carregadas de '{config_path}'. Caminho de rede: {SHARED_NETWORK_PATH}, Intervalo: {COLLECTION_INTERVAL_SECONDS}s, Apelido da Máquina: '{MACHINE_ALIAS}'")
        return config  # ← retorna o config real
    except json.JSONDecodeError:
        logger.error(f"Erro ao decodificar JSON do arquivo de configuração '{config_path}'. Verifique o formato. Usando valores padrão.")
        default_config = {
            "SHARED_NETWORK_PATH": r"\\10.10.10.61\ti\SIA",
            "COLLECTION_INTERVAL_SECONDS": 10,
            "MACHINE_ALIAS": ""
        }
        SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
        COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
        MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
        return default_config
    except Exception as e:
        logger.error(f"Erro inesperado ao carregar arquivo de configuração '{config_path}': {e}. Usando valores padrão.")
        default_config = {
            "SHARED_NETWORK_PATH": r"\\10.10.10.61\ti\SIA",
            "COLLECTION_INTERVAL_SECONDS": 10,
            "MACHINE_ALIAS": ""
        }
        SHARED_NETWORK_PATH = default_config["SHARED_NETWORK_PATH"]
        COLLECTION_INTERVAL_SECONDS = default_config["COLLECTION_INTERVAL_SECONDS"]
        MACHINE_ALIAS = default_config["MACHINE_ALIAS"]
        return default_config

# --- Funções de Coleta de Hardware ---

def get_cpu_info():
    cpu_percent = psutil.cpu_percent(interval=None) 
    cpu_cores_physical = psutil.cpu_count(logical=False)
    cpu_cores_logical = psutil.cpu_count(logical=True)
    cpu_freq = psutil.cpu_freq()
    cpu_name = platform.processor()

    cpu_info = {
        "percentual_uso": cpu_percent,
        "nucleos_fisicos": cpu_cores_physical,
        "nucleos_logicos": cpu_cores_logical,
        "frequencia_mhz": cpu_freq.current if cpu_freq else None,
        "nome": cpu_name,
        "temperatura_package_celsius": None,
        "temperaturas_cores_celsius": {},
        "uso_total_percent": None,
        "energia_watts": None,
        "clocks_mhz": None
    }

    if platform.system() == "Windows" and has_wmi:
        try:
            c = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            # Buscar informações da CPU pelo OHM, se disponível
            hardware_info = c.Hardware()
            for hw in hardware_info:
                if hw.HardwareType.lower() == "cpu":
                    cpu_info['nome'] = hw.Name
                    sensors_wmi = c.Sensor(Parent=hw.Identifier)
                    temp_sensors_data = {}
                    for sensor in sensors_wmi:
                        sensor_type = sensor.SensorType.lower()
                        sensor_name_key = sensor.Name.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").replace("#", "").lower()
                        if sensor_type not in temp_sensors_data:
                            temp_sensors_data[sensor_type] = {}
                        temp_sensors_data[sensor_type][sensor_name_key] = round(sensor.Value, 2)
                    
                    if 'temperature' in temp_sensors_data:
                        if 'cpu_package' in temp_sensors_data['temperature']:
                            cpu_info['temperatura_package_celsius'] = temp_sensors_data['temperature']['cpu_package']
                        core_temps = {}
                        for k, v in temp_sensors_data['temperature'].items():
                            if 'cpu_core' in k:
                                core_temps[k] = v
                        if core_temps:
                            cpu_info['temperaturas_cores_celsius'] = core_temps
                    if 'load' in temp_sensors_data:
                         cpu_info['uso_total_percent'] = temp_sensors_data['load'].get('cpu_total')
                    if 'power' in temp_sensors_data:
                        cpu_info['energia_watts'] = temp_sensors_data['power']
                    if 'clock' in temp_sensors_data:
                        cpu_info['clocks_mhz'] = temp_sensors_data['clock']
                    break
        except wmi.x_wmi as e:
            logger.warning(f"Erro WMI ao obter dados detalhados da CPU via OHM: {e}")
        except Exception as e:
            logger.warning(f"Erro inesperado ao obter dados detalhados da CPU via OHM: {e}")
    elif platform.system() == "Linux" and hasattr(psutil, "sensors_temperatures"):
        temps = psutil.sensors_temperatures()
        if temps:
            cpu_temp = temps.get('coretemp') or temps.get('cpu_thermal')
            if cpu_temp:
                cpu_info['temperatura_package_celsius'] = cpu_temp[0].current if cpu_temp else None
                core_temps = {}
                for i, entry in enumerate(cpu_temp):
                    if 'current' in entry._fields: # Ensure 'current' attribute exists
                        core_temps[f"core_{entry.label or i+1}"] = entry.current
                if core_temps:
                    cpu_info['temperaturas_cores_celsius'] = core_temps
            logger.info("Temperaturas básicas da CPU coletadas via psutil (Linux).")
        else:
            logger.info("Linux: psutil.sensors_temperatures() retornou vazio ou não é suportado.")
            
    return cpu_info

def get_ram_info():
    mem = psutil.virtual_memory()
    return {
        "total_gb": round(mem.total / (1024**3), 2),
        "usado_gb": round(mem.used / (1024**3), 2),
        "percentual_uso": mem.percent
    }

def get_disk_info():
    import psutil
    import platform
    import wmi
    import logging

    logger = logging.getLogger(__name__)
    main_disk = {}
    additional_disks = []

    partitions = psutil.disk_partitions(all=False)

    # Mapeia discos físicos a partições lógicas via WMI
    device_to_model_map = {}
    try:
        wmi_root = wmi.WMI()
        for disk in wmi_root.Win32_DiskDrive():
            for partition in disk.associators("Win32_DiskDriveToDiskPartition"):
                for logical_disk in partition.associators("Win32_LogicalDiskToPartition"):
                    device_to_model_map[logical_disk.DeviceID + "\\"] = disk.Model.strip()
    except Exception as e:
        logger.warning(f"Erro ao mapear discos físicos via WMI padrão: {e}")

    # Pré-carrega discos físicos via OHM
    hw_disks = []
    c_ohm = None
    if platform.system() == "Windows" and has_wmi:
        try:
            c_ohm = wmi.WMI(namespace="root\\OpenHardwareMonitor")
            hw_disks = [hw for hw in c_ohm.Hardware() if hw.HardwareType.lower() == "hdd"]
        except Exception as e:
            logger.warning(f"Erro ao obter hardware via OHM: {e}")

    for i, partition in enumerate(partitions):
        if 'cdrom' in partition.opts or partition.fstype == '':
            continue
        try:
            usage = psutil.disk_usage(partition.mountpoint)

            # Obtém nome real do disco (via WMI tradicional)
            nome_real = device_to_model_map.get(partition.device, partition.device)

            disk_entry = {
                "particao": partition.device,
                "nome": nome_real,
                "total_gb": round(usage.total / (1024**3), 2),
                "usado_gb": round(usage.used / (1024**3), 2),
                "livre_gb": round(usage.free / (1024**3), 2),
                "percentual_uso": usage.percent,
                "uso_espaco_percent": usage.percent,
                "temperatura_celsius": None,
                "vida_util_restante_percent": None,
                "dados_gravados_tb": None,
                "tipo": None
            }

            # Associa dados de sensores via OHM, ainda por índice (melhorado depois)
            if c_ohm and i < len(hw_disks):
                try:
                    hw = hw_disks[i]
                    ohm_nome = hw.Name.replace(" (", "").replace(")", "").strip()
                    disk_entry["tipo"] = (
                        "HDD" if "hdd" in ohm_nome.lower()
                        else "SSD" if "ssd" in ohm_nome.lower()
                        else "Desconhecido"
                    )

                    sensors_wmi = c_ohm.Sensor(Parent=hw.Identifier)
                    temp_sensors_data = {}
                    for sensor in sensors_wmi:
                        sensor_type = sensor.SensorType.lower()
                        sensor_name_key = (
                            sensor.Name.replace(" ", "_")
                                .replace("(", "")
                                .replace(")", "")
                                .replace("-", "_")
                                .replace("#", "")
                                .lower()
                        )
                        if sensor_type not in temp_sensors_data:
                            temp_sensors_data[sensor_type] = {}
                        temp_sensors_data[sensor_type][sensor_name_key] = round(sensor.Value, 2)

                    if 'temperature' in temp_sensors_data and 'temperature' in temp_sensors_data['temperature']:
                        disk_entry['temperatura_celsius'] = temp_sensors_data['temperature']['temperature']
                    if 'level' in temp_sensors_data and 'remaining_life' in temp_sensors_data['level']:
                        disk_entry['vida_util_restante_percent'] = temp_sensors_data['level']['remaining_life']
                    if 'data' in temp_sensors_data and 'total_bytes_written' in temp_sensors_data['data']:
                        disk_entry['dados_gravados_tb'] = round(temp_sensors_data['data']['total_bytes_written'] / (1024**4), 2)

                except Exception as e:
                    logger.warning(f"Erro OHM para partição {partition.device}: {e}")

            if i == 0:
                main_disk = disk_entry
            else:
                additional_disks.append(disk_entry)

        except Exception as e:
            logger.warning(f"Não foi possível obter informações do disco para {partition.mountpoint}: {e}")

    return main_disk, additional_disks



def get_gpu_info():
    gpu_data = {
        "nome": None,
        "tipo": None,
        "temperatura_core_celsius": None,
        "uso_percentual": None,
        "memoria_gpu": {"usada_mb": None, "livre_mb": None, "total_mb": None},
        "clocks_mhz": {}
    }

    if platform.system() == "Windows" and has_wmi:
        ohm_wmi_conn = get_ohm_data()
        if ohm_wmi_conn:
            ohm_gpu_info = get_gpu_info_ohm(ohm_wmi_conn)
            if ohm_gpu_info:
                # Assuming single main GPU, take the first one
                gpu_data = ohm_gpu_info[0] # Take the first GPU data
    
    # Fallback/Additional pynvml data if available (e.g. for non-OHM scenarios or more precise data)
    if has_pynvml and gpu_data["nome"] is None: # Only if OHM didn't fill it
        try:
            nvmlInit()
            device_count = nvmlDeviceGetCount()
            if device_count > 0:
                handle = nvmlDeviceGetHandleByIndex(0) # Get first GPU
                gpu_data["nome"] = nvmlDeviceGetName(handle).decode('utf-8')
                gpu_data["tipo"] = "NVIDIA"
                
                # Get memory info
                mem_info = nvmlDeviceGetMemoryInfo(handle)
                gpu_data["memoria_gpu"]["total_mb"] = round(mem_info.total / (1024**2), 2)
                gpu_data["memoria_gpu"]["usada_mb"] = round(mem_info.used / (1024**2), 2)
                gpu_data["memoria_gpu"]["livre_mb"] = round(mem_info.free / (1024**2), 2)

                # Get utilization
                util = nvmlDeviceGetUtilizationRates(handle)
                gpu_data["uso_percentual"] = util.gpu
                
                # Get temperature
                temp = nvmlDeviceGetTemperature(handle, NVML_TEMP_GPU)
                gpu_data["temperatura_core_celsius"] = temp

                # Get clocks (example, specific clocks can vary)
                # gpu_data["clocks_mhz"]["graphics"] = nvmlDeviceGetClockInfo(handle, NVML_CLOCK_GRAPHICS, NVML_CLOCK_ID_CURRENT)
                # gpu_data["clocks_mhz"]["memory"] = nvmlDeviceGetClockInfo(handle, NVML_CLOCK_MEM, NVML_CLOCK_ID_CURRENT)

        except NVMLError as error:
            logger.warning(f"Erro pynvml ao obter dados da GPU: {error}")
        finally:
            if has_pynvml:
                try:
                    nvmlShutdown()
                except NVMLError:
                    pass

    return gpu_data


def get_network_info():
    net_io_before = psutil.net_io_counters()
    time.sleep(1)
    net_io_after = psutil.net_io_counters()

    bytes_sent_diff = net_io_after.bytes_sent - net_io_before.bytes_sent
    bytes_recv_diff = net_io_after.bytes_recv - net_io_before.bytes_recv

    send_speed_mbps = round((bytes_sent_diff * 8) / 1_000_000, 2)
    recv_speed_mbps = round((bytes_recv_diff * 8) / 1_000_000, 2)
    total_speed_mbps = round(send_speed_mbps + recv_speed_mbps, 2)

    # Captura de todos os IPs IPv4 por interface
    ip_por_interface = {}
    for nome_iface, infos in psutil.net_if_addrs().items():
        for info in infos:
            if info.family.name == 'AF_INET' and info.address != '127.0.0.1':
                ip_por_interface[nome_iface] = info.address

    return {
        "ips": ip_por_interface,
        "bytes_enviados_mb": round(net_io_after.bytes_sent / (1024**2), 2),
        "bytes_recebidos_mb": round(net_io_after.bytes_recv / (1024**2), 2),
        "velocidade_atual_mbps": total_speed_mbps
    }

def get_motherboard_info():
    motherboard_info = {"nome": None}
    if platform.system() == "Windows" and has_wmi:
        try:
            c = wmi.WMI() # Connect to default WMI namespace
            for board in c.Win32_BaseBoard():
                motherboard_info["nome"] = board.Product
                break
        except Exception as e:
            logger.warning(f"Erro ao obter informações da placa-mãe via WMI: {e}")
    return motherboard_info

def get_system_uptime_hours():
    uptime_seconds = time.time() - psutil.boot_time()
    uptime_hours = round(uptime_seconds / 3600, 2)
    return uptime_hours

# Windows specific (using WMI for OpenHardwareMonitor data)
def get_ohm_data():
    if platform.system() == "Windows" and has_wmi:
        try:
            return wmi.WMI(namespace="root\\OpenHardwareMonitor")
        except wmi.x_wmi as e:
            logger.warning(f"Erro WMI ao conectar ao OpenHardwareMonitor. Verifique se o OHM está rodando e o namespace está acessível: {e}")
        except Exception as e:
            logger.error(f"Erro inesperado ao tentar conectar ao OpenHardwareMonitor via WMI: {e}")
    return None

def get_gpu_info_ohm(ohm_wmi_conn):
    gpu_info_list = [] # Return as list to match previous structure, but take first for main GPU
    if ohm_wmi_conn is not None:
        try:
            hardware_info = ohm_wmi_conn.Hardware()
            for hw in hardware_info:
                if "gpu" in hw.HardwareType.lower():
                    gpu_entry = {
                        "nome": hw.Name,
                        "tipo": hw.HardwareType,
                        "temperatura_core_celsius": None,
                        "uso_percentual": None,
                        "memoria_gpu": {"usada_mb": None, "livre_mb": None, "total_mb": None},
                        "clocks_mhz": {}
                    }
                    sensors_wmi = ohm_wmi_conn.Sensor(Parent=hw.Identifier)
                    temp_sensors_data = {}
                    for sensor in sensors_wmi:
                        sensor_type = sensor.SensorType.lower()
                        sensor_name_key = sensor.Name.replace(" ", "_").replace("(", "").replace(")", "").replace("-", "_").replace("#", "").lower()
                        if sensor_type not in temp_sensors_data:
                            temp_sensors_data[sensor_type] = {}
                        temp_sensors_data[sensor_type][sensor_name_key] = round(sensor.Value, 2)
                    
                    if 'temperature' in temp_sensors_data and 'gpu_core' in temp_sensors_data['temperature']:
                        gpu_entry['temperatura_core_celsius'] = temp_sensors_data['temperature']['gpu_core']
                    if 'load' in temp_sensors_data and 'gpu_core' in temp_sensors_data['load']:
                        gpu_entry['uso_percentual'] = temp_sensors_data['load']['gpu_core']
                    if 'smalldata' in temp_sensors_data: 
                        gpu_entry['memoria_gpu'] = {
                            "usada_mb": temp_sensors_data['smalldata'].get('gpu_memory_used'),
                            "livre_mb": temp_sensors_data['smalldata'].get('gpu_memory_free'),
                            "total_mb": temp_sensors_data['smalldata'].get('gpu_memory_total')
                        }
                    if 'clock' in temp_sensors_data:
                        gpu_entry['clocks_mhz'] = temp_sensors_data['clock']
                    gpu_info_list.append(gpu_entry)
        except wmi.x_wmi as e:
            logger.warning(f"Erro WMI ao obter dados da GPU via OHM: {e}")
        except Exception as e:
            logger.warning(f"Erro inesperado ao obter dados da GPU via OHM: {e}")
    return gpu_info_list

# --- Get Top Processes (CPU, RAM, GPU) ---
def get_top_processes(num_processes=3):
    processes_cpu = []
    processes_ram = []
    processes_gpu = []

    all_psutil_procs = []
    for p in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_percent']):
        try:
            p.cpu_percent(interval=None) # Prime the CPU %
            all_psutil_procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue
    
    time.sleep(0.1) 

    for p in all_psutil_procs:
        try:
            cpu_usage = p.cpu_percent(interval=None)
            ram_usage = p.memory_percent()
            process_name = p.name()

            processes_cpu.append({'pid': p.pid, 'name': process_name, 'cpu_percent': cpu_usage})
            processes_ram.append({'pid': p.pid, 'name': process_name, 'memory_percent': ram_usage})
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    processes_cpu_sorted = sorted(processes_cpu, key=lambda x: x['cpu_percent'], reverse=True)
    top_cpu = processes_cpu_sorted[:num_processes]

    processes_ram_sorted = sorted(processes_ram, key=lambda x: x['memory_percent'], reverse=True)
    top_ram = processes_ram_sorted[:num_processes]

    # --- GPU collection using pynvml ---
    if has_pynvml:
        try:
            nvmlInit()
            device_count = nvmlDeviceGetCount()

            for i in range(device_count):
                handle = nvmlDeviceGetHandleByIndex(i)
                device_name = nvmlDeviceGetName(handle).decode('utf-8')
                
                gpu_processes_on_device = []
                try:
                    gpu_processes_on_device.extend(nvmlDeviceGetComputeRunningProcesses(handle))
                except NVMLError as err:
                    if err.returnCode == NVML_ERROR_NOT_SUPPORTED:
                        logger.debug(f"Compute process monitoring not supported on GPU {i} ({device_name}).")
                    else:
                        logger.error(f"Error getting compute processes for GPU {i}: {err}", exc_info=True)
                try:
                    gpu_processes_on_device.extend(nvmlDeviceGetGraphicsRunningProcesses(handle))
                except NVMLError as err:
                     if err.returnCode == NVML_ERROR_NOT_SUPPORTED:
                        logger.debug(f"Graphics process monitoring not supported on GPU {i} ({device_name}).")
                     else:
                        logger.error(f"Error getting graphics processes for GPU {i}: {err}", exc_info=True)

                seen_pids = set()

                for proc in gpu_processes_on_device:
                    if proc.pid not in seen_pids:
                        seen_pids.add(proc.pid)
                        try:
                            p = psutil.Process(proc.pid)
                            process_name = p.name()
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            process_name = "Unknown"

                        processes_gpu.append({
                            'pid': proc.pid,
                            'name': process_name,
                            'gpu_id': i,
                            'gpu_name': device_name,
                            'gpu_memory_mb': round(proc.usedGpuMemory / (1024 * 1024), 2)
                        })

        except NVMLError as error:
            logger.warning(f"NVIDIA GPU monitoring error (NVML not available or no NVIDIA GPU found): {error}")
            processes_gpu = []
        finally:
            if has_pynvml:
                try:
                    nvmlShutdown()
                except NVMLError:
                    pass

    processes_gpu_sorted = sorted(processes_gpu, key=lambda x: x.get('gpu_memory_mb', 0), reverse=True)
    top_gpu = processes_gpu_sorted[:num_processes]

    return {
        "top_cpu_processes": top_cpu,
        "top_ram_processes": top_ram,
        "top_gpu_processes": top_gpu
    }


def collect_all_data():
    """Coleta os dados de hardware e sistema e os consolida em um único objeto."""
    
    final_data = {}
    
    main_disk, additional_disks = get_disk_info()
    
    monitoramento_data = {
        "cpu": get_cpu_info(), 
        "memoria_ram": get_ram_info(), 
        "disco_principal": main_disk,
        "discos_adicionais": additional_disks,
        "gpu": get_gpu_info(), # Agora retorna um único objeto GPU
        "rede": get_network_info(),
        "placa_mae": get_motherboard_info(),
        "uptime_horas": get_system_uptime_hours(), # Uptime em horas
        "top_processos": get_top_processes(3) # Inclui os top processos
    }

    try:
        final_data['hostname'] = platform.node()
        final_data['machine_alias'] = MACHINE_ALIAS if MACHINE_ALIAS else final_data['hostname']
        final_data['timestamp_coleta'] = datetime.datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        final_data['monitoramento'] = monitoramento_data

    except Exception as e:
        logger.error(f"Erro geral ao coletar dados de hardware: {e}", exc_info=True)
        return None
    
    return final_data


# --- Funções de Bloqueio de Arquivo ---
# Use um arquivo .lock separado para bloqueio, mais robusto para msvcrt
def acquire_file_lock(data_file_path, timeout_seconds=10, check_interval_seconds=0.1):
    """
    Tenta adquirir um bloqueio de arquivo. Cria um arquivo .lock auxiliar.
    Retorna o descritor de arquivo do .lock se o bloqueio for adquirido, None caso contrário.
    """
    lock_file_path = data_file_path + ".lock"
    start_time = time.time()

    if platform.system() == "Windows":
        if msvcrt is None:
            logger.error("msvcrt não está disponível, bloqueio de arquivo no Windows não suportado.")
            return None
        
        while time.time() - start_time < timeout_seconds:
            try:
                # Tenta criar o arquivo de lock em modo exclusivo e travá-lo.
                # os.open com os.O_CREAT | os.O_EXCL garante que só uma instância crie
                fd = os.open(lock_file_path, os.O_CREAT | os.O_EXCL | os.O_RDWR)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1) # Bloqueio não-bloqueante para testar
                logger.debug(f"Bloqueio adquirido para: {lock_file_path}")
                return fd # Retorna o descritor do arquivo .lock
            except FileExistsError:
                logger.debug(f"Arquivo de lock '{lock_file_path}' já existe. Esperando...")
            except (IOError, OSError) as e: # Catch permission errors, etc.
                logger.debug(f"Erro ao tentar bloquear '{lock_file_path}': {e}. Esperando...")
            except Exception as e:
                logger.warning(f"Erro inesperado ao adquirir bloqueio para '{lock_file_path}': {e}. Esperando...")
            time.sleep(check_interval_seconds)
        
        logger.error(f"Não foi possível adquirir bloqueio para '{data_file_path}' após {timeout_seconds} segundos.")
        return None
    else: # Linux/macOS using fcntl
        import fcntl
        while time.time() - start_time < timeout_seconds:
            try:
                fd = os.open(lock_file_path, os.O_CREAT | os.O_RDWR)
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB) # LOCK_EX (exclusive), LOCK_NB (non-blocking)
                logger.debug(f"Bloqueio adquirido para: {lock_file_path}")
                return fd
            except (IOError, OSError) as e: # Resource temporarily unavailable if already locked
                logger.debug(f"Não foi possível adquirir bloqueio para '{lock_file_path}': {e}. Esperando...")
            except Exception as e:
                logger.warning(f"Erro inesperado ao tentar adquirir bloqueio para '{lock_file_path}': {e}. Esperando...")
            time.sleep(check_interval_seconds)
        logger.error(f"Não foi possível adquirir bloqueio para '{data_file_path}' após {timeout_seconds} segundos.")
        return None

def release_file_lock(lock_fd, data_file_path):
    """Libera o bloqueio de arquivo e remove o arquivo .lock."""
    lock_file_path = data_file_path + ".lock"
    if lock_fd is None:
        return # Nothing to release
    
    if platform.system() == "Windows":
        if msvcrt is None: return
        try:
            msvcrt.locking(lock_fd, msvcrt.LK_UNLCK, 1) # Desbloqueia
            os.close(lock_fd) # Fecha o descritor
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
            logger.debug(f"Bloqueio liberado e arquivo .lock removido: {lock_file_path}")
        except Exception as e:
            logger.error(f"Erro ao liberar bloqueio para '{lock_file_path}': {e}")
    else: # Linux/macOS using fcntl
        import fcntl
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN) # Libera o bloqueio
            os.close(lock_fd) # Fecha o descritor
            if os.path.exists(lock_file_path):
                os.remove(lock_file_path)
            logger.debug(f"Bloqueio liberado e arquivo .lock removido: {lock_file_path}")
        except Exception as e:
            logger.error(f"Erro ao liberar bloqueio para '{lock_file_path}': {e}")


import requests

def write_data_to_files(data, base_path, config):
    """
    Escreve os dados coletados em:
    1. Acumula os dados em um JSON individual da máquina ([MACHINE_ALIAS].json).
    2. Adiciona uma entrada ao JSON geral mensal (dados_gerais_mensal.json).
    3. Envia os dados para uma API REST se habilitado.
    Implementa retries com backoff e um bloqueio de arquivo simples.
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

    def _write_json_with_retries(file_full_path, data_to_append, is_general_json=False):
        current_backoff = INITIAL_BACKOFF_SECONDS
        lock_fd = None
        for attempt in range(MAX_RETRIES):
            try:
                lock_fd = acquire_file_lock(file_full_path, timeout_seconds=INITIAL_BACKOFF_SECONDS)
                if lock_fd is None:
                    raise Exception("Não foi possível adquirir o bloqueio de arquivo.")

                content_list = []

                if os.path.exists(file_full_path) and os.path.getsize(file_full_path) > 0:
                    with open(file_full_path, 'r', encoding='utf-8') as f_read:
                        content = f_read.read()
                        if content:
                            try:
                                content_list = json.loads(content)
                                if not isinstance(content_list, list):
                                    raise ValueError(f"Conteúdo de JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' não é uma lista.")
                            except json.JSONDecodeError as e:
                                logger.warning(f"JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' corrompido: {e}. O arquivo será recriado. (Tentativa {attempt + 1}/{MAX_RETRIES})")
                            except Exception as e:
                                logger.warning(f"Erro inesperado ao ler JSON {'geral' if is_general_json else 'individual'} '{file_full_path}': {e}. (Tentativa {attempt + 1}/{MAX_RETRIES})")
                                content_list = []

                content_list.append(data_to_append)

                with open(file_full_path, 'w', encoding='utf-8') as f_write:
                    json.dump(content_list, f_write, indent=4)

                logger.info(f"✅ JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' atualizado com sucesso na tentativa {attempt + 1}.")
                return True

            except Exception as e:
                log_message = f"Não foi possível processar/escrever JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' na tentativa {attempt + 1}/{MAX_RETRIES}: {e}. Tentando novamente em {current_backoff:.2f} segundos."
                if attempt == MAX_RETRIES - 1:
                    logger.error(log_message, exc_info=True)
                else:
                    logger.warning(log_message)
            finally:
                if lock_fd:
                    release_file_lock(lock_fd, file_full_path)
                    lock_fd = None

            sleep_time = current_backoff + random.uniform(0, current_backoff * 0.1)
            time.sleep(min(sleep_time, MAX_BACKOFF_SECONDS))
            current_backoff *= 2

        logger.critical(f"❌ Falha CRÍTICA ao atualizar JSON {'geral' if is_general_json else 'individual'} '{file_full_path}' após {MAX_RETRIES} tentativas. Os dados não foram salvos.")
        return False

    success_individual = False
    success_general = False
    api_sent = False

    # Tenta envio via API se ativado
    if config.get("API", False) and config.get("APIURL"):
        try:
            response = requests.post(
                config["APIURL"],
                json=data,
                headers={"Content-Type": "application/json"},
                timeout=10
            )
            if response.status_code == 201:
                api_sent = True
                logger.info(f"📤 Dados enviados com sucesso para API em {config['APIURL']}.")
            else:
                logger.warning(f"❌ API retornou status {response.status_code}: {response.text}")
        except requests.RequestException as e:
            logger.error(f"❌ Erro ao enviar dados para API REST: {e}")

    # Se LOCAL estiver ativado ou API falhar, grava os arquivos
    if config.get("LOCAL", True) or not api_sent:
        if not config.get("LOCAL", True) and not api_sent:
            logger.warning("⚠️ LOCAL estava desativado, mas como o envio para a API falhou, os dados serão salvos localmente.")
        success_individual = _write_json_with_retries(individual_path, data, is_general_json=False)
        success_general = _write_json_with_retries(general_path, data, is_general_json=True)
    else:
        logger.info("🧾 Dados enviados via API com sucesso. Armazenamento local desativado.")

    return success_individual or api_sent

    # --- Chamadas das funções auxiliares ---

    individual_full_path = os.path.join(monthly_path, f"{file_identifier}.json")
    if not _write_json_with_retries(individual_full_path, data, is_general_json=False):
        return False 

    general_full_path = os.path.join(monthly_path, "dados_gerais_mensal.json")
    return _write_json_with_retries(general_full_path, data, is_general_json=True)


# --- Execução principal do script ---
if __name__ == '__main__':
    # Carrega as configurações ao iniciar o script
    config = load_configuration()
    if not config:
        logger.error("Falha ao carregar a configuração inicial. Encerrando.")
        sys.exit(1)

    logger.info("Iniciando o agente de monitoramento.")
    logger.info(f"Os dados serão salvos em: {os.path.abspath(SHARED_NETWORK_PATH)}")

    while True:
        try:
            collected_data = collect_all_data()
            if collected_data:
                if not write_data_to_files(collected_data, SHARED_NETWORK_PATH, config):
                    logger.error("Erro ao salvar dados coletados. Verifique permissões e logs de arquivo.")
            else:
                logger.error("Não foi possível coletar dados de hardware. Verifique o log para detalhes.")

            logger.info(f"Próxima coleta em {COLLECTION_INTERVAL_SECONDS} segundos...")
            time.sleep(COLLECTION_INTERVAL_SECONDS)

        except KeyboardInterrupt:
            logger.info("Monitoramento interrompido pelo usuário (Ctrl+C). Encerrando.")
            break
        except Exception as e:
            logger.critical(f"Um erro inesperado ocorreu no loop principal: {e}", exc_info=True)
            logger.info(f"Tentando novamente em {COLLECTION_INTERVAL_SECONDS} segundos...")
            time.sleep(COLLECTION_INTERVAL_SECONDS)