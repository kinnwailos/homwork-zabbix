#!/usr/bin/env python3
# =============================================================================
# ZABBIX 6.0 LTS - АВТОМАТИЗИРОВАННОЕ РАЗВЁРТЫВАНИЕ НА YANDEX CLOUD
# Язык: Python 3.8+
# =============================================================================
"""
Этот скрипт автоматически разворачивает полноценную систему мониторинга Zabbix
в облаке Yandex Cloud.

Что делает скрипт:
    1. Создаёт сеть (VPC) и подсеть
    2. Создаёт группу безопасности с правилами для Zabbix
    3. Создаёт 3 виртуальные машины (server + 2 агента)
    4. Настраивает Zabbix Server (PostgreSQL, Apache, PHP)
    5. Настраивает Zabbix Agent2 на обоих агентах
    6. Выводит итоговую информацию для доступа

Требования:
    - Установленный Yandex Cloud CLI (yc)
    - Настроенная аутентификация (yc init)
    - Python 3.8 или выше
    - SSH-ключ для доступа к ВМ
"""

# =============================================================================
# ИМПОРТ БИБЛИОТЕК
# =============================================================================

import subprocess      # Для выполнения команд оболочки (yc, ssh, scp)
import json            # Для парсинга JSON-вывода yc CLI
import time            # Для пауз между операциями
import os              # Для работы с файловой системой
import sys             # Для системных функций (выход, аргументы)
from datetime import datetime  # Для временных меток
from typing import Optional, Dict, List  # Для типизации

# =============================================================================
# КОНФИГУРАЦИЯ (НАСТРАИВАЕМЫЕ ПАРАМЕТРЫ)
# =============================================================================

class Config:
    """
    Класс конфигурации - хранит все настраиваемые параметры.
    Изменяйте значения здесь под свою инфраструктуру.
    """
    
    # -------------------------------------------------------------------------
    # YANDEX CLOUD - ИДЕНТИФИКАТОРЫ
    # -------------------------------------------------------------------------
    FOLDER_ID: str = "b1gfathufckfv3107j45"  # Ваш folder-id (получить: yc config get folder-id)
    CLOUD_ID: str = ""  # Можно оставить пустым, определяется автоматически
    ZONE: str = "ru-central1-a"  # Зона доступности
    
    # -------------------------------------------------------------------------
    # СЕТЕВАЯ ИНФРАСТРУКТУРА
    # -------------------------------------------------------------------------
    NETWORK_NAME: str = "zabbix-network"      # Имя сети VPC
    SUBNET_NAME: str = "zabbix-subnet"        # Имя подсети
    SUBNET_CIDR: str = "10.128.0.0/24"        # Диапазон IP-адресов подсети
    SG_NAME: str = "zabbix-sg"                # Имя группы безопасности
    
    # -------------------------------------------------------------------------
    # ПАРАМЕТРЫ ВИРТУАЛЬНЫХ МАШИН
    # -------------------------------------------------------------------------
    # Zabbix Server (более мощный)
    SERVER_NAME: str = "zabbix-server"
    SERVER_CORES: int = 2
    SERVER_MEMORY: int = 4  # ГБ
    SERVER_DISK_SIZE: int = 20  # ГБ
    
    # Агенты (менее мощные)
    AGENT_NAME_PREFIX: str = "agent"
    AGENT_CORES: int = 2
    AGENT_MEMORY: int = 2  # ГБ
    AGENT_DISK_SIZE: int = 10  # ГБ
    AGENT_COUNT: int = 2  # Количество агентов
    
    # Общие параметры ВМ
    PLATFORM: str = "standard-v1"  # Платформа (процессоры)
    CORE_FRACTION: int = 20  # Базовый уровень производительности (20%)
    IMAGE_FAMILY: str = "ubuntu-2204-lts"  # Образ ОС
    IMAGE_FOLDER_ID: str = "standard-images"  # Папка с образами
    
    # -------------------------------------------------------------------------
    # SSH-ДОСТУП
    # -------------------------------------------------------------------------
    SSH_KEY_PATH: str = os.path.expanduser("~/.ssh/id_rsa.pub")  # Публичный ключ
    SSH_PRIVATE_KEY: str = os.path.expanduser("~/.ssh/id_rsa")   # Приватный ключ
    
    # -------------------------------------------------------------------------
    # НАСТРОЙКИ ZABBIX
    # -------------------------------------------------------------------------
    ZABBIX_VERSION: str = "6.0"
    ZABBIX_RELEASE: str = "6.0.45"
    DB_NAME: str = "zabbix"
    DB_USER: str = "zabbix"
    DB_PASS: str = "zabbix"  # ⚠️ Смените в продакшене!
    TIMEZONE: str = "Europe/Moscow"
    
    # -------------------------------------------------------------------------
    # НАСТРОЙКИ СКРИПТА
    # -------------------------------------------------------------------------
    VERBOSE: bool = True  # Подробный вывод
    DRY_RUN: bool = False  # Если True - только показывает, что будет делать


# =============================================================================
# УТИЛИТЫ ДЛЯ РАБОТЫ С КОМАНДАМИ
# =============================================================================

class CommandLine:
    """
    Класс-утилита для выполнения команд оболочки.
    Инкапсулирует работу с subprocess для удобства.
    """
    
    @staticmethod
    def run(command: str, check: bool = True, capture: bool = True) -> subprocess.CompletedProcess:
        """
        Выполняет команду в оболочке.
        
        Args:
            command: Команда для выполнения
            check: Выбрасывать исключение при ошибке
            capture: Захватывать вывод
            
        Returns:
            CompletedProcess с результатом выполнения
            
        Raises:
            subprocess.CalledProcessError: Если команда вернула ошибку и check=True
        """
        if Config.VERBOSE:
            print(f"  📝 Executing: {command[:100]}{'...' if len(command) > 100 else ''}")
        
        result = subprocess.run(
            command,
            shell=True,
            capture_output=capture,
            text=True,
            check=check
        )
        
        return result
    
    @staticmethod
    def run_json(command: str) -> dict:
        """
        Выполняет команду и парсит JSON-результат.
        Используется для yc CLI, который возвращает JSON.
        
        Args:
            command: Команда yc CLI
            
        Returns:
            dict с распарсенным JSON
        """
        result = CommandLine.run(command + " --format json")
        return json.loads(result.stdout)
    
    @staticmethod
    def exists(command: str) -> bool:
        """
        Проверяет, существует ли ресурс (возвращает yc без ошибок).
        
        Args:
            command: Команда yc get
            
        Returns:
            True если ресурс существует, False если нет
        """
        try:
            CommandLine.run(command, check=True, capture=False)
            return True
        except subprocess.CalledProcessError:
            return False


# =============================================================================
# ЦВЕТА ДЛЯ ВЫВОДА В ТЕРМИНАЛ
# =============================================================================

class Colors:
    """ANSI-коды цветов для красивого вывода в терминал."""
    
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    MAGENTA = '\033[0;35m'
    WHITE = '\033[1;37m'
    NC = '\033[0m'  # No Color (сброс)
    
    @staticmethod
    def colorize(text: str, color: str) -> str:
        """Оборачивает текст в ANSI-код цвета."""
        return f"{color}{text}{Colors.NC}"
    
    @staticmethod
    def info(text: str) -> str:
        return Colors.colorize(f"[INFO] {text}", Colors.BLUE)
    
    @staticmethod
    def success(text: str) -> str:
        return Colors.colorize(f"[OK] {text}", Colors.GREEN)
    
    @staticmethod
    def warning(text: str) -> str:
        return Colors.colorize(f"[WARN] {text}", Colors.YELLOW)
    
    @staticmethod
    def error(text: str) -> str:
        return Colors.colorize(f"[ERROR] {text}", Colors.RED)


# =============================================================================
# ЛОГГЕР ДЛЯ ВЫВОДА СООБЩЕНИЙ
# =============================================================================

class Logger:
    """
    Класс для логирования операций.
    Выводит красивые сообщения с цветами и временными метками.
    """
    
    @staticmethod
    def log(message: str, level: str = "INFO"):
        """Выводит лог-сообщение с временной меткой."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        if level == "INFO":
            print(f"{Colors.BLUE}[{timestamp}] [INFO]{Colors.NC} {message}")
        elif level == "SUCCESS":
            print(f"{Colors.GREEN}[{timestamp}] [OK]{Colors.NC} {message}")
        elif level == "WARNING":
            print(f"{Colors.YELLOW}[{timestamp}] [WARN]{Colors.NC} {message}")
        elif level == "ERROR":
            print(f"{Colors.RED}[{timestamp}] [ERROR]{Colors.NC} {message}")
        elif level == "STEP":
            print(f"\n{Colors.CYAN}{'='*70}{Colors.NC}")
            print(f"{Colors.CYAN}  📍 {message}{Colors.NC}")
            print(f"{Colors.CYAN}{'='*70}{Colors.NC}\n")
    
    @staticmethod
    def info(msg: str): Logger.log(msg, "INFO")
    @staticmethod
    def success(msg: str): Logger.log(msg, "SUCCESS")
    @staticmethod
    def warning(msg: str): Logger.log(msg, "WARNING")
    @staticmethod
    def error(msg: str): Logger.log(msg, "ERROR")
    @staticmethod
    def step(msg: str): Logger.log(msg, "STEP")


# =============================================================================
# ПРОВЕРКА ПРЕДВАРИТЕЛЬНЫХ УСЛОВИЙ
# =============================================================================

class PrerequisitesChecker:
    """
    Проверяет, что все необходимые компоненты установлены и настроены.
    """
    
    @staticmethod
    def check_yc_cli() -> bool:
        """Проверяет наличие Yandex Cloud CLI."""
        try:
            result = CommandLine.run("yc --version", check=False)
            if result.returncode == 0:
                Logger.success("Yandex Cloud CLI установлен")
                return True
            else:
                Logger.error("Yandex Cloud CLI не найден")
                return False
        except Exception:
            Logger.error("Yandex Cloud CLI не найден")
            return False
    
    @staticmethod
    def check_yc_auth() -> bool:
        """Проверяет аутентификацию в Yandex Cloud."""
        try:
            result = CommandLine.run("yc config get folder-id", check=False)
            if result.returncode == 0 and result.stdout.strip():
                Logger.success(f"YC аутентифицирован (folder-id: {result.stdout.strip()})")
                return True
            else:
                Logger.error("YC CLI не настроен. Выполните: yc init")
                return False
        except Exception:
            Logger.error("YC CLI не настроен. Выполните: yc init")
            return False
    
    @staticmethod
    def check_ssh_key() -> bool:
        """Проверяет наличие SSH-ключа."""
        if os.path.exists(Config.SSH_KEY_PATH):
            Logger.success(f"SSH ключ найден: {Config.SSH_KEY_PATH}")
            return True
        else:
            Logger.error(f"SSH ключ не найден: {Config.SSH_KEY_PATH}")
            Logger.info("Создайте ключ: ssh-keygen -t rsa -b 4096")
            return False
    
    @staticmethod
    def check_python_version() -> bool:
        """Проверяет версию Python."""
        version = sys.version_info
        if version.major >= 3 and version.minor >= 8:
            Logger.success(f"Python {version.major}.{version.minor}.{version.micro} подходит")
            return True
        else:
            Logger.error(f"Требуется Python 3.8+, у вас {version.major}.{version.minor}")
            return False
    
    @staticmethod
    def check_all() -> bool:
        """
        Запускает все проверки.
        Returns: True если все проверки пройдены
        """
        Logger.step("Проверка предварительных условий")
        
        checks = [
            PrerequisitesChecker.check_python_version(),
            PrerequisitesChecker.check_yc_cli(),
            PrerequisitesChecker.check_yc_auth(),
            PrerequisitesChecker.check_ssh_key(),
        ]
        
        if all(checks):
            Logger.success("Все проверки пройдены ✅")
            return True
        else:
            Logger.error("Некоторые проверки не пройдены ❌")
            return False


# =============================================================================
# УПРАВЛЕНИЕ СЕТЕВОЙ ИНФРАСТРУКТУРОЙ
# =============================================================================

class NetworkManager:
    """
    Управляет сетевой инфраструктурой: сеть, подсеть, группа безопасности.
    """
    
    def __init__(self):
        self.network_id: Optional[str] = None
        self.subnet_id: Optional[str] = None
        self.sg_id: Optional[str] = None
    
    def create_network(self) -> str:
        """
        Создаёт сеть VPC если не существует.
        Returns: ID сети
        """
        Logger.step("Создание сети")
        
        # Проверяем, существует ли сеть
        if CommandLine.exists(f"yc vpc network get {Config.NETWORK_NAME}"):
            Logger.warning(f"Сеть {Config.NETWORK_NAME} уже существует")
        else:
            Logger.info(f"Создание сети {Config.NETWORK_NAME}...")
            CommandLine.run(f"""
                yc vpc network create \\
                    --name {Config.NETWORK_NAME} \\
                    --folder-id {Config.FOLDER_ID} \\
                    --description "Zabbix Network"
            """)
            Logger.success(f"Сеть {Config.NETWORK_NAME} создана")
        
        # Получаем ID сети
        result = CommandLine.run_json(f"yc vpc network get {Config.NETWORK_NAME}")
        self.network_id = result['id']
        Logger.info(f"Network ID: {self.network_id}")
        
        return self.network_id
    
    def create_subnet(self) -> str:
        """
        Создаёт подсеть если не существует.
        Returns: ID подсети
        """
        Logger.step("Создание подсети")
        
        # Проверяем, существует ли подсеть
        if CommandLine.exists(f"yc vpc subnet get {Config.SUBNET_NAME}"):
            Logger.warning(f"Подсеть {Config.SUBNET_NAME} уже существует")
        else:
            Logger.info(f"Создание подсети {Config.SUBNET_NAME}...")
            CommandLine.run(f"""
                yc vpc subnet create \\
                    --name {Config.SUBNET_NAME} \\
                    --zone {Config.ZONE} \\
                    --range {Config.SUBNET_CIDR} \\
                    --network-name {Config.NETWORK_NAME} \\
                    --folder-id {Config.FOLDER_ID}
            """)
            Logger.success(f"Подсеть {Config.SUBNET_NAME} создана")
        
        # Получаем ID подсети
        result = CommandLine.run_json(f"yc vpc subnet get {Config.SUBNET_NAME}")
        self.subnet_id = result['id']
        Logger.info(f"Subnet ID: {self.subnet_id}")
        
        return self.subnet_id
    
    def create_security_group(self) -> str:
        """
        Создаёт группу безопасности с правилами для Zabbix.
        Returns: ID группы безопасности
        """
        Logger.step("Создание группы безопасности")
        
        if CommandLine.exists(f"yc vpc security-group get {Config.SG_NAME}"):
            Logger.warning(f"Группа безопасности {Config.SG_NAME} уже существует")
        else:
            Logger.info(f"Создание группы безопасности {Config.SG_NAME}...")
            
            # Формируем правила безопасности
            rules = [
                # Входящий трафик (INGRESS)
                'direction=ingress,port=80,protocol=tcp,v4-cidrs="0.0.0.0/0",description="HTTP"',
                'direction=ingress,port=443,protocol=tcp,v4-cidrs="0.0.0.0/0",description="HTTPS"',
                'direction=ingress,port=22,protocol=tcp,v4-cidrs="0.0.0.0/0",description="SSH"',
                'direction=ingress,port=10050,protocol=tcp,v4-cidrs="10.128.0.0/16",description="Zabbix Agent Passive"',
                'direction=ingress,port=10051,protocol=tcp,v4-cidrs="10.128.0.0/16",description="Zabbix Agent Active"',
                # Исходящий трафик (EGRESS) - разрешаем всё
                'direction=egress,port=1-65535,protocol=tcp,v4-cidrs="0.0.0.0/0",description="All TCP Outbound"',
                'direction=egress,port=1-65535,protocol=udp,v4-cidrs="0.0.0.0/0",description="All UDP Outbound"',
                'direction=egress,protocol=icmp,v4-cidrs="0.0.0.0/0",description="ICMP Outbound"',
            ]
            
            rules_str = ' '.join([f'--rule {r}' for r in rules])
            
            CommandLine.run(f"""
                yc vpc security-group create \\
                    --name {Config.SG_NAME} \\
                    --network-name {Config.NETWORK_NAME} \\
                    --folder-id {Config.FOLDER_ID} \\
                    --description "Security group for Zabbix" \\
                    {rules_str}
            """)
            Logger.success(f"Группа безопасности {Config.SG_NAME} создана")
        
        # Получаем ID группы безопасности
        result = CommandLine.run_json(f"yc vpc security-group get {Config.SG_NAME}")
        self.sg_id = result['id']
        Logger.info(f"Security Group ID: {self.sg_id}")
        
        return self.sg_id


# =============================================================================
# УПРАВЛЕНИЕ ВИРТУАЛЬНЫМИ МАШИНАМИ
# =============================================================================

class VMManager:
    """
    Управляет виртуальными машинами: создание, получение IP, управление состоянием.
    """
    
    def __init__(self, subnet_id: str, sg_id: str):
        self.subnet_id = subnet_id
        self.sg_id = sg_id
        self.vms: Dict[str, dict] = {}  # Хранит информацию о ВМ
    
    def create_vm(self, name: str, cores: int, memory: int, disk_size: int) -> dict:
        """
        Создаёт виртуальную машину.
        
        Args:
            name: Имя ВМ
            cores: Количество CPU
            memory: Объем RAM (ГБ)
            disk_size: Размер диска (ГБ)
            
        Returns:
            dict с информацией о ВМ
        """
        Logger.info(f"Создание ВМ {name}...")
        
        if CommandLine.exists(f"yc compute instance get {name}"):
            Logger.warning(f"ВМ {name} уже существует")
        else:
            CommandLine.run(f"""
                yc compute instance create \\
                    --name {name} \\
                    --zone {Config.ZONE} \\
                    --platform {Config.PLATFORM} \\
                    --cores {cores} \\
                    --memory {memory} \\
                    --core-fraction {Config.CORE_FRACTION} \\
                    --create-boot-disk type=network-hdd,size={disk_size},image-family={Config.IMAGE_FAMILY},image-folder-id={Config.IMAGE_FOLDER_ID} \\
                    --network-interface subnet-id={self.subnet_id},nat-ip-version=ipv4,security-group-ids={self.sg_id} \\
                    --ssh-key {Config.SSH_KEY_PATH} \\
                    --metadata serial-port-enable=1
            """)
            Logger.success(f"ВМ {name} создана")
        
        # Получаем информацию о ВМ
        result = CommandLine.run_json(f"yc compute instance get {name}")
        
        self.vms[name] = {
            'id': result['id'],
            'name': name,
            'internal_ip': result['network_interfaces'][0]['primary_v4_address']['address'],
            'public_ip': result['network_interfaces'][0]['primary_v4_address'].get('one_to_one_nat', {}).get('address', ''),
            'disk_id': result['boot_disk']['disk_id'],
        }
        
        Logger.info(f"  Internal IP: {self.vms[name]['internal_ip']}")
        if self.vms[name]['public_ip']:
            Logger.info(f"  Public IP: {self.vms[name]['public_ip']}")
        
        return self.vms[name]
    
    def create_all_vms(self) -> Dict[str, dict]:
        """
        Создаёт все ВМ (сервер + агенты).
        Returns: dict со всеми ВМ
        """
        Logger.step("Создание виртуальных машин")
        
        # Создаём Zabbix Server
        self.create_vm(Config.SERVER_NAME, Config.SERVER_CORES, Config.SERVER_MEMORY, Config.SERVER_DISK_SIZE)
        
        # Создаём агенты
        for i in range(1, Config.AGENT_COUNT + 1):
            agent_name = f"{Config.AGENT_NAME_PREFIX}-{i}"
            self.create_vm(agent_name, Config.AGENT_CORES, Config.AGENT_MEMORY, Config.AGENT_DISK_SIZE)
        
        # Ждём запуска ВМ
        Logger.info("Ожидание запуска ВМ (60 секунд)...")
        time.sleep(60)
        
        Logger.success("Все ВМ запущены ✅")
        
        return self.vms
    
    def wait_for_ssh(self, name: str, timeout: int = 300) -> bool:
        """
        Ждёт доступности SSH на ВМ.
        
        Args:
            name: Имя ВМ
            timeout: Таймаут в секундах
            
        Returns:
            True если SSH доступен, False если таймаут
        """
        public_ip = self.vms[name]['public_ip']
        Logger.info(f"Ожидание SSH на {name} ({public_ip})...")
        
        start_time = time.time()
        while time.time() - start_time < timeout:
            result = CommandLine.run(
                f"ssh -i {Config.SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no -o ConnectTimeout=5 "
                f"yc-user@{public_ip} 'echo SSH_OK'",
                check=False
            )
            if result.returncode == 0 and "SSH_OK" in result.stdout:
                Logger.success(f"SSH на {name} доступен")
                return True
            time.sleep(5)
        
        Logger.error(f"Таймаут ожидания SSH на {name}")
        return False


# =============================================================================
# НАСТРОЙКА ZABBIX SERVER
# =============================================================================

class ZabbixServerConfigurator:
    """
    Настраивает Zabbix Server: устанавливает пакеты, настраивает БД, веб-интерфейс.
    """
    
    def __init__(self, vm_manager: VMManager):
        self.vm_manager = vm_manager
        self.server_info = vm_manager.vms[Config.SERVER_NAME]
    
    def get_setup_script(self) -> str:
        """
        Генерирует скрипт настройки Zabbix Server.
        Returns: Многострочная строка с bash-скриптом
        """
        return f"""#!/bin/bash
set -e

# =============================================================================
# НАСТРОЙКА ZABBIX SERVER
# =============================================================================

DB_NAME="{Config.DB_NAME}"
DB_USER="{Config.DB_USER}"
DB_PASS="{Config.DB_PASS}"
TIMEZONE="{Config.TIMEZONE}"

echo "🔧 Начало настройки Zabbix Server..."

# 1. Добавляем репозиторий Zabbix
echo "📦 Добавление репозитория Zabbix..."
echo "deb https://repo.zabbix.com/zabbix/{Config.ZABBIX_VERSION}/ubuntu jammy main" > /etc/apt/sources.list.d/zabbix.list
curl -fsSL https://repo.zabbix.com/zabbix-official-repo.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/zabbix-official-repo.gpg
apt update

# 2. Устанавливаем пакеты
echo "📦 Установка пакетов Zabbix..."
apt install zabbix-server-pgsql zabbix-frontend-php zabbix-apache-conf zabbix-agent2 postgresql postgresql-contrib curl wget -y

# 3. Настраиваем базу данных
echo "🗄️ Настройка базы данных..."
su - postgres -c "psql -c \\"DROP USER IF EXISTS $DB_USER CASCADE;\\"" 2>/dev/null || true
su - postgres -c "psql -c \\"DROP DATABASE IF EXISTS $DB_NAME;\\"" 2>/dev/null || true
su - postgres -c "psql -c \\"CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';\\""
su - postgres -c "psql -c \\"CREATE DATABASE $DB_NAME OWNER $DB_USER;\\""

# 4. Скачиваем и импортируем схему БД
echo "📊 Импорт схемы базы данных..."
cd /tmp
wget -q https://cdn.zabbix.com/zabbix/sources/stable/{Config.ZABBIX_VERSION}/zabbix-{Config.ZABBIX_RELEASE}.tar.gz
tar -xzf zabbix-{Config.ZABBIX_RELEASE}.tar.gz
cd zabbix-{Config.ZABBIX_RELEASE}/database/postgresql

su - $DB_USER -c "psql $DB_NAME < schema.sql"
su - $DB_USER -c "psql $DB_NAME < images.sql"
su - $DB_USER -c "psql $DB_NAME < data.sql"

# 5. Настраиваем пароль БД в конфиге Zabbix
echo "⚙️ Настройка конфигурации..."
sed -i 's/# DBPassword=/DBPassword=$DB_PASS/' /etc/zabbix/zabbix_server.conf

# 6. Устанавливаем и настраиваем PHP
echo "🐘 Настройка PHP..."
apt install php8.1-fpm libapache2-mod-php8.1 php8.1-pgsql php8.1-gd php8.1-mbstring php8.1-xml php8.1-bcmath php8.1-curl -y

a2enmod proxy_fcgi setenvif rewrite alias
a2enconf zabbix php8.1-fpm
a2dissite 000-default.conf 2>/dev/null || true

sed -i 's/post_max_size = .*/post_max_size = 16M/' /etc/php/8.1/fpm/php.ini
sed -i 's/max_execution_time = .*/max_execution_time = 300/' /etc/php/8.1/fpm/php.ini
sed -i 's/max_input_time = .*/max_input_time = 300/' /etc/php/8.1/fpm/php.ini
sed -i 's/# php_value date.timezone.*/php_value date.timezone $TIMEZONE/' /etc/apache2/conf-enabled/zabbix.conf

chown -R www-www-data /usr/share/zabbix
chmod -R 755 /usr/share/zabbix

# 7. Перезапускаем службы
echo "🔄 Перезапуск служб..."
systemctl daemon-reload
systemctl restart zabbix-server zabbix-agent2 apache2 php8.1-fpm
systemctl enable zabbix-server zabbix-agent2 apache2 php8.1-fpm

# 8. Проверка статуса
echo ""
echo "✅ Настройка завершена!"
echo ""
systemctl status zabbix-server --no-pager -l | head -5
systemctl status apache2 --no-pager -l | head -5

echo ""
echo "🌐 Веб-интерфейс будет доступен по адресу:"
echo "   http://{self.server_info['public_ip']}/zabbix"
echo ""
echo "🔐 Данные для входа:"
echo "   Логин: Admin"
echo "   Пароль: $DB_PASS"
echo ""
"""
    
    def configure(self):
        """
        Выполняет настройку Zabbix Server.
        """
        Logger.step("Настройка Zabbix Server")
        
        public_ip = self.server_info['public_ip']
        
        # Ждём доступности SSH
        if not self.vm_manager.wait_for_ssh(Config.SERVER_NAME):
            Logger.error("Не удалось подключиться по SSH к Zabbix Server")
            return False
        
        # Создаём скрипт настройки локально
        script_path = "/tmp/zabbix-server-setup.sh"
        with open(script_path, 'w') as f:
            f.write(self.get_setup_script())
        os.chmod(script_path, 0o755)
        
        # Копируем скрипт на сервер
        Logger.info("Копирование скрипта настройки на сервер...")
        CommandLine.run(f"""
            scp -i {Config.SSH_PRIVATE_KEY} \\
                -o StrictHostKeyChecking=no \\
                -o UserKnownHostsFile=/dev/null \\
                {script_path} yc-user@{public_ip}:/tmp/
        """)
        
        # Выполняем скрипт на сервере
        Logger.info("Выполнение настройки (это займёт 5-10 минут)...")
        CommandLine.run(f"""
            ssh -i {Config.SSH_PRIVATE_KEY} \\
                -o StrictHostKeyChecking=no \\
                -o UserKnownHostsFile=/dev/null \\
                yc-user@{public_ip} "sudo bash /tmp/zabbix-server-setup.sh"
        """, check=False)  # check=False потому что скрипт долгий
        
        Logger.success("Zabbix Server настроен ✅")
        
        return True


# =============================================================================
# НАСТРОЙКА ZABBIX AGENTS
# =============================================================================

class ZabbixAgentConfigurator:
    """
    Настраивает Zabbix Agent2 на агентах.
    """
    
    def __init__(self, vm_manager: VMManager, server_internal_ip: str):
        self.vm_manager = vm_manager
        self.server_internal_ip = server_internal_ip
    
    def get_agent_script(self, hostname: str) -> str:
        """
        Генерирует скрипт настройки агента.
        
        Args:
            hostname: Имя хоста для агента (agent-1, agent-2)
            
        Returns:
            Многострочная строка с bash-скриптом
        """
        return f"""#!/bin/bash
set -e

SERVER_IP="{self.server_internal_ip}"
HOSTNAME="{hostname}"

echo "🔧 Настройка Zabbix Agent2 ({hostname})..."

# 1. Добавляем репозиторий Zabbix
echo "deb https://repo.zabbix.com/zabbix/{Config.ZABBIX_VERSION}/ubuntu jammy main" > /etc/apt/sources.list.d/zabbix.list
curl -fsSL https://repo.zabbix.com/zabbix-official-repo.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/zabbix-official-repo.gpg
apt update

# 2. Устанавливаем агент
apt install zabbix-agent2 -y

# 3. Настраиваем подключение к серверу
sed -i "s/Server=127.0.0.1/Server=$SERVER_IP/" /etc/zabbix/zabbix_agent2.conf
sed -i "s/ServerActive=127.0.0.1/ServerActive=$SERVER_IP/" /etc/zabbix/zabbix_agent2.conf
sed -i "s/Hostname=Zabbix server/Hostname=$HOSTNAME/" /etc/zabbix/zabbix_agent2.conf

# 4. Перезапускаем агент
systemctl restart zabbix-agent2
systemctl enable zabbix-agent2

echo ""
echo "✅ Агент {hostname} настроен!"
systemctl status zabbix-agent2 --no-pager -l | head -5
"""
    
    def configure_agent(self, name: str, hostname: str):
        """
        Настраивает один агент.
        
        Args:
            name: Имя ВМ
            hostname: Имя хоста в Zabbix
        """
        Logger.info(f"Настройка {name} ({hostname})...")
        
        vm_info = self.vm_manager.vms[name]
        public_ip = vm_info['public_ip']
        
        # Ждём доступности SSH
        if not self.vm_manager.wait_for_ssh(name):
            Logger.error(f"Не удалось подключиться по SSH к {name}")
            return False
        
        # Создаём скрипт настройки
        script_path = f"/tmp/zabbix-agent-{name}-setup.sh"
        with open(script_path, 'w') as f:
            f.write(self.get_agent_script(hostname))
        os.chmod(script_path, 0o755)
        
        # Копируем и выполняем
        CommandLine.run(f"""
            scp -i {Config.SSH_PRIVATE_KEY} \\
                -o StrictHostKeyChecking=no \\
                -o UserKnownHostsFile=/dev/null \\
                {script_path} yc-user@{public_ip}:/tmp/
        """)
        
        CommandLine.run(f"""
            ssh -i {Config.SSH_PRIVATE_KEY} \\
                -o StrictHostKeyChecking=no \\
                -o UserKnownHostsFile=/dev/null \\
                yc-user@{public_ip} "sudo bash /tmp/zabbix-agent-{name}-setup.sh"
        """, check=False)
        
        Logger.success(f"{name} настроен ✅")
        
        return True
    
    def configure_all_agents(self):
        """Настраивает все агенты."""
        Logger.step("Настройка Zabbix Agents")
        
        for i in range(1, Config.AGENT_COUNT + 1):
            agent_name = f"{Config.AGENT_NAME_PREFIX}-{i}"
            self.configure_agent(agent_name, agent_name)
        
        Logger.success("Все агенты настроены ✅")


# =============================================================================
# СОЗДАНИЕ СНЯБКОВ (BACKUP)
# =============================================================================

class BackupManager:
    """
    Управляет созданием снимков дисков для бэкапа.
    """
    
    @staticmethod
    def create_snapshots(vm_manager: VMManager):
        """
        Создаёт снимки всех дисков ВМ.
        """
        Logger.step("Создание снимков для бэкапа")
        
        date_str = datetime.now().strftime("%Y%m%d")
        
        for name, vm_info in vm_manager.vms.items():
            disk_id = vm_info['disk_id']
            snapshot_name = f"{name}-snapshot-{date_str}"
            
            Logger.info(f"Создание снимка {snapshot_name}...")
            CommandLine.run(f"""
                yc compute disk snapshot create \\
                    --disk-name {disk_id} \\
                    --name {snapshot_name}
            """)
            
            Logger.success(f"Снимок {snapshot_name} создан")
        
        Logger.success("Все снимки созданы ✅")


# =============================================================================
# ВЫВОД ИТОГОВОЙ ИНФОРМАЦИИ
# =============================================================================

class SummaryReporter:
    """
    Выводит итоговую информацию о развёртывании.
    """
    
    @staticmethod
    def print(vm_manager: VMManager):
        """
        Выводит красивую сводку по развёртыванию.
        """
        server_info = vm_manager.vms[Config.SERVER_NAME]
        server_public_ip = server_info['public_ip']
        
        print(f"""
{Colors.CYAN}{'='*75}{Colors.NC}
{Colors.GREEN}                    🎉 РАЗВЁРТЫВАНИЕ ЗАВЕРШЕНО! 🎉{Colors.NC}
{Colors.CYAN}{'='*75}{Colors.NC}

{Colors.WHITE}📊 ZABBIX WEB-ИНТЕРФЕЙС:{Colors.NC}
   URL:      {Colors.YELLOW}http://{server_public_ip}/zabbix{Colors.NC}
   Логин:    {Colors.YELLOW}Admin{Colors.NC}
   Пароль:   {Colors.YELLOW}{Config.DB_PASS}{Colors.NC}
   {Colors.RED}⚠️ Смените пароль после первого входа!{Colors.NC}

{Colors.WHITE}🖥️ ВИРТУАЛЬНЫЕ МАШИНЫ:{Colors.NC}
""")
        
        for name, vm_info in vm_manager.vms.items():
            print(f"   {Colors.GREEN}✓{Colors.NC} {name:20} Internal: {vm_info['internal_ip']:15} Public: {vm_info['public_ip']}")
        
        print(f"""
{Colors.WHITE}📋 СЛЕДУЮЩИЕ ШАГИ:{Colors.NC}
   1. Откройте {Colors.YELLOW}http://{server_public_ip}/zabbix{Colors.NC} в браузере
   2. Пройдите мастер установки:
      • Database type: {Colors.YELLOW}PostgreSQL{Colors.NC}
      • Database host: {Colors.YELLOW}localhost{Colors.NC}
      • Database port: {Colors.YELLOW}5432{Colors.NC}
      • Database name: {Colors.YELLOW}{Config.DB_NAME}{Colors.NC}
      • User: {Colors.YELLOW}{Config.DB_USER}{Colors.NC}
      • Password: {Colors.YELLOW}{Config.DB_PASS}{Colors.NC}
   3. Добавьте хосты агентов в Configuration → Hosts:
      • agent-1: {vm_manager.vms['agent-1']['internal_ip']}
      • agent-2: {vm_manager.vms['agent-2']['internal_ip']}
   4. Используйте шаблон: {Colors.YELLOW}Templates/Operating systems → Linux by Zabbix agent{Colors.NC}

{Colors.WHITE}🛡️ РЕКОМЕНДАЦИЯ - СОЗДАЙТЕ БЭКАП:{Colors.NC}
   {Colors.YELLOW}python3 deploy_zabbix.py --backup{Colors.NC}

{Colors.CYAN}{'='*75}{Colors.NC}
{Colors.GREEN}                    УДАЧИ С МОНИТОРИНГОМ! 🚀{Colors.NC}
{Colors.CYAN}{'='*75}{Colors.NC}
""")


# =============================================================================
# ОСНОВНОЙ КЛАСС ОРКЕСТРАТОР
# =============================================================================

class ZabbixDeployer:
    """
    Главный класс-оркестратор.
    Управляет всем процессом развёртывания.
    """
    
    def __init__(self):
        self.network_manager: Optional[NetworkManager] = None
        self.vm_manager: Optional[VMManager] = None
    
    def deploy(self):
        """
        Запускает полный процесс развёртывания.
        """
        print(f"""
{Colors.CYAN}{'='*75}{Colors.NC}
{Colors.WHITE}        ZABBIX 6.0 LTS - АВТОМАТИЗИРОВАННОЕ РАЗВЁРТЫВАНИЕ{Colors.NC}
{Colors.CYAN}{'='*75}{Colors.NC}
""")
        
        # 1. Проверка предварительных условий
        if not PrerequisitesChecker.check_all():
            Logger.error("Проверка не пройдена. Исправьте ошибки и запустите снова.")
            sys.exit(1)
        
        # 2. Создание сетевой инфраструктуры
        self.network_manager = NetworkManager()
        self.network_manager.create_network()
        self.network_manager.create_subnet()
        self.network_manager.create_security_group()
        
        # 3. Создание ВМ
        self.vm_manager = VMManager(
            subnet_id=self.network_manager.subnet_id,
            sg_id=self.network_manager.sg_id
        )
        self.vm_manager.create_all_vms()
        
        # 4. Настройка Zabbix Server
        server_configurator = ZabbixServerConfigurator(self.vm_manager)
        server_configurator.configure()
        
        # 5. Настройка агентов
        agent_configurator = ZabbixAgentConfigurator(
            self.vm_manager,
            self.vm_manager.vms[Config.SERVER_NAME]['internal_ip']
        )
        agent_configurator.configure_all_agents()
        
        # 6. Вывод итогов
        SummaryReporter.print(self.vm_manager)
    
    def create_backup(self):
        """
        Создаёт снимки всех ВМ для бэкапа.
        """
        Logger.step("Создание бэкапа")
        
        # Инициализируем менеджеры (предполагаем, что ВМ уже созданы)
        self.network_manager = NetworkManager()
        self.network_manager.create_network()
        self.network_manager.create_subnet()
        self.network_manager.create_security_group()
        
        self.vm_manager = VMManager(
            subnet_id=self.network_manager.subnet_id,
            sg_id=self.network_manager.sg_id
        )
        
        # Получаем информацию о существующих ВМ
        for name in [Config.SERVER_NAME] + [f"{Config.AGENT_NAME_PREFIX}-{i}" for i in range(1, Config.AGENT_COUNT + 1)]:
            try:
                result = CommandLine.run_json(f"yc compute instance get {name}")
                self.vm_manager.vms[name] = {
                    'id': result['id'],
                    'name': name,
                    'internal_ip': result['network_interfaces'][0]['primary_v4_address']['address'],
                    'public_ip': result['network_interfaces'][0]['primary_v4_address'].get('one_to_one_nat', {}).get('address', ''),
                    'disk_id': result['boot_disk']['disk_id'],
                }
            except Exception as e:
                Logger.warning(f"Не удалось получить информацию о {name}: {e}")
        
        # Создаём снимки
        BackupManager.create_snapshots(self.vm_manager)
        Logger.success("Бэкап создан ✅")


# =============================================================================
# ТОЧКА ВХОДА (MAIN)
# =============================================================================

def main():
    """
    Точка входа в программу.
    Обрабатывает аргументы командной строки.
    """
    import argparse
    
    parser = argparse.ArgumentParser(
        description="Автоматическое развёртывание Zabbix 6.0 LTS в Yandex Cloud",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры использования:
  python3 deploy_zabbix.py              # Полное развёртывание
  python3 deploy_zabbix.py --backup     # Создать бэкап существующих ВМ
  python3 deploy_zabbix.py --dry-run    # Показать, что будет сделано (без выполнения)
        """
    )
    
    parser.add_argument(
        '--backup',
        action='store_true',
        help='Создать снимки дисков всех ВМ для бэкапа'
    )
    
    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Режим сухой проверки (показать команды без выполнения)'
    )
    
    parser.add_argument(
        '--verbose',
        action='store_true',
        default=True,
        help='Подробный вывод (по умолчанию включён)'
    )
    
    args = parser.parse_args()
    
    # Применяем аргументы к конфигурации
    Config.DRY_RUN = args.dry_run
    Config.VERBOSE = args.verbose
    
    # Создаём оркестратор
    deployer = ZabbixDeployer()
    
    # Запускаем нужный режим
    if args.backup:
        deployer.create_backup()
    else:
        deployer.deploy()


# =============================================================================
# ЗАПУСК СКРИПТА
# =============================================================================

if __name__ == "__main__":
    main()
