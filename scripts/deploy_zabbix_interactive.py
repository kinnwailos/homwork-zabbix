#!/usr/bin/env python3
# =============================================================================
# ZABBIX 6.0 LTS - ИНТЕРАКТИВНОЕ РАЗВЁРТЫВАНИЕ (РУЧНОЙ РЕЖИМ)
# =============================================================================
"""
Эта версия скрипта запрашивает подтверждение перед каждым шагом.
Идеально для обучения и контроля процесса.
"""

import subprocess
import json
import time
import os
import sys
from datetime import datetime
from typing import Optional, Dict

# =============================================================================
# КОНФИГУРАЦИЯ
# =============================================================================

class Config:
    FOLDER_ID: str = "b1gfathufckfv3107j45"
    ZONE: str = "ru-central1-a"
    NETWORK_NAME: str = "zabbix-network"
    SUBNET_NAME: str = "zabbix-subnet"
    SUBNET_CIDR: str = "10.128.0.0/24"
    SG_NAME: str = "zabbix-sg"
    SERVER_NAME: str = "zabbix-server"
    AGENT_COUNT: int = 2
    SSH_KEY_PATH: str = os.path.expanduser("~/.ssh/id_rsa.pub")
    SSH_PRIVATE_KEY: str = os.path.expanduser("~/.ssh/id_rsa")
    DB_NAME: str = "zabbix"
    DB_USER: str = "zabbix"
    DB_PASS: str = "zabbix"

# =============================================================================
# ЦВЕТА И ЛОГГЕР
# =============================================================================

class Colors:
    RED = '\033[0;31m'
    GREEN = '\033[0;32m'
    YELLOW = '\033[1;33m'
    BLUE = '\033[0;34m'
    CYAN = '\033[0;36m'
    NC = '\033[0m'

class Logger:
    @staticmethod
    def step(msg: str):
        print(f"\n{Colors.CYAN}{'='*70}{Colors.NC}")
        print(f"{Colors.CYAN}  📍 {msg}{Colors.NC}")
        print(f"{Colors.CYAN}{'='*70}{Colors.NC}\n")

    @staticmethod
    def info(msg: str):
        print(f"{Colors.BLUE}[INFO]{Colors.NC} {msg}")

    @staticmethod
    def success(msg: str):
        print(f"{Colors.GREEN}[OK]{Colors.NC} {msg}")

    @staticmethod
    def warning(msg: str):
        print(f"{Colors.YELLOW}[WARN]{Colors.NC} {msg}")

    @staticmethod
    def error(msg: str):
        print(f"{Colors.RED}[ERROR]{Colors.NC} {msg}")

# =============================================================================
# ИНТЕРАКТИВНЫЕ ПРОВЕРКИ
# =============================================================================

def ask_confirmation(step_name: str) -> bool:
    """
    Запрашивает подтверждение у пользователя перед шагом.
    """
    print(f"\n{Colors.YELLOW}⚠️  ШАГ: {step_name}{Colors.NC}")
    response = input("Продолжить? (y/n): ").strip().lower()
    return response == 'y' or response == 'yes' or response == ''

def run_command(command: str, check: bool = True) -> subprocess.CompletedProcess:
    """Выполняет команду и показывает вывод."""
    Logger.info(f"Выполнение: {command[:80]}{'...' if len(command) > 80 else ''}")
    result = subprocess.run(command, shell=True, capture_output=True, text=True, check=check)
    if result.stdout:
        print(result.stdout)
    if result.stderr and result.returncode != 0:
        print(result.stderr)
    return result

def run_json(command: str) -> dict:
    """Выполняет команду и парсит JSON."""
    result = run_command(command + " --format json")
    return json.loads(result.stdout)

# =============================================================================
# ПРОВЕРКА УСЛОВИЙ
# =============================================================================

def check_prerequisites_interactive():
    """Интерактивная проверка условий."""
    Logger.step("ПРОВЕРКА ПРЕДВАРИТЕЛЬНЫХ УСЛОВИЙ")

    checks = [
        ("YC CLI установлен", "yc --version"),
        ("YC аутентифицирован", "yc config get folder-id"),
        ("SSH-ключ существует", f"test -f {Config.SSH_KEY_PATH}"),
        ("Python 3.8+", "python3 --version"),
    ]

    all_passed = True
    for name, cmd in checks:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
        if result.returncode == 0:
            Logger.success(f"✓ {name}")
        else:
            Logger.error(f"✗ {name}")
            all_passed = False

    if not all_passed:
        Logger.error("Некоторые проверки не пройдены. Исправьте и запустите снова.")
        sys.exit(1)

    Logger.success("Все проверки пройдены ✅")

# =============================================================================
# СЕТЕВАЯ ИНФРАСТРУКТУРА
# =============================================================================

def create_network_interactive():
    """Создание сети с подтверждением."""
    if not ask_confirmation(f"Создать сеть '{Config.NETWORK_NAME}'"):
        Logger.warning("Пропущено по выбору пользователя")
        return None

    if subprocess.run(f"yc vpc network get {Config.NETWORK_NAME}", shell=True, capture_output=True).returncode == 0:
        Logger.warning("Сеть уже существует")
    else:
        run_command(f"""
            yc vpc network create \\
                --name {Config.NETWORK_NAME} \\
                --folder-id {Config.FOLDER_ID} \\
                --description "Zabbix Network"
        """)
        Logger.success("Сеть создана")

    result = run_json(f"yc vpc network get {Config.NETWORK_NAME}")
    return result['id']

def create_subnet_interactive(network_id: str):
    """Создание подсети с подтверждением."""
    if not ask_confirmation(f"Создать подсеть '{Config.SUBNET_NAME}'"):
        Logger.warning("Пропущено по выбору пользователя")
        return None

    if subprocess.run(f"yc vpc subnet get {Config.SUBNET_NAME}", shell=True, capture_output=True).returncode == 0:
        Logger.warning("Подсеть уже существует")
    else:
        run_command(f"""
            yc vpc subnet create \\
                --name {Config.SUBNET_NAME} \\
                --zone {Config.ZONE} \\
                --range {Config.SUBNET_CIDR} \\
                --network-name {Config.NETWORK_NAME} \\
                --folder-id {Config.FOLDER_ID}
        """)
        Logger.success("Подсеть создана")

    result = run_json(f"yc vpc subnet get {Config.SUBNET_NAME}")
    return result['id']

def create_security_group_interactive():
    """Создание группы безопасности с подтверждением."""
    if not ask_confirmation(f"Создать группу безопасности '{Config.SG_NAME}'"):
        Logger.warning("Пропущено по выбору пользователя")
        return None

    if subprocess.run(f"yc vpc security-group get {Config.SG_NAME}", shell=True, capture_output=True).returncode == 0:
        Logger.warning("Группа безопасности уже существует")
    else:
        rules = [
            'direction=ingress,port=80,protocol=tcp,v4-cidrs="0.0.0.0/0"',
            'direction=ingress,port=22,protocol=tcp,v4-cidrs="0.0.0.0/0"',
            'direction=ingress,port=10050,protocol=tcp,v4-cidrs="10.128.0.0/16"',
            'direction=ingress,port=10051,protocol=tcp,v4-cidrs="10.128.0.0/16"',
            'direction=egress,port=1-65535,protocol=tcp,v4-cidrs="0.0.0.0/0"',
            'direction=egress,port=1-65535,protocol=udp,v4-cidrs="0.0.0.0/0"',
            'direction=egress,protocol=icmp,v4-cidrs="0.0.0.0/0"',
        ]
        rules_str = ' '.join([f'--rule {r}' for r in rules])

        run_command(f"""
            yc vpc security-group create \\
                --name {Config.SG_NAME} \\
                --network-name {Config.NETWORK_NAME} \\
                --folder-id {Config.FOLDER_ID} \\
                --description "Security group for Zabbix" \\
                {rules_str}
        """)
        Logger.success("Группа безопасности создана")

    result = run_json(f"yc vpc security-group get {Config.SG_NAME}")
    return result['id']

# =============================================================================
# ВИРТУАЛЬНЫЕ МАШИНЫ
# =============================================================================

def create_vm_interactive(name: str, cores: int, memory: int, disk_size: int, subnet_id: str, sg_id: str):
    """Создание ВМ с подтверждением."""
    if not ask_confirmation(f"Создать ВМ '{name}' ({cores} CPU, {memory}GB RAM, {disk_size}GB disk)"):
        Logger.warning("Пропущено по выбору пользователя")
        return None

    if subprocess.run(f"yc compute instance get {name}", shell=True, capture_output=True).returncode == 0:
        Logger.warning(f"ВМ {name} уже существует")
    else:
        run_command(f"""
            yc compute instance create \\
                --name {name} \\
                --zone {Config.ZONE} \\
                --platform standard-v1 \\
                --cores {cores} \\
                --memory {memory} \\
                --core-fraction 20 \\
                --create-boot-disk type=network-hdd,size={disk_size},image-family=ubuntu-2204-lts,image-folder-id=standard-images \\
                --network-interface subnet-id={subnet_id},nat-ip-version=ipv4,security-group-ids={sg_id} \\
                --ssh-key {Config.SSH_KEY_PATH} \\
                --metadata serial-port-enable=1
        """)
        Logger.success(f"ВМ {name} создана")

    result = run_json(f"yc compute instance get {name}")
    return {
        'name': name,
        'internal_ip': result['network_interfaces'][0]['primary_v4_address']['address'],
        'public_ip': result['network_interfaces'][0]['primary_v4_address'].get('one_to_one_nat', {}).get('address', ''),
        'disk_id': result['boot_disk']['disk_id'],
    }

def create_all_vms_interactive(subnet_id: str, sg_id: str):
    """Создание всех ВМ."""
    Logger.step("СОЗДАНИЕ ВИРТУАЛЬНЫХ МАШИН")

    vms = {}

    # Zabbix Server
    vms[Config.SERVER_NAME] = create_vm_interactive(
        Config.SERVER_NAME, 2, 4, 20, subnet_id, sg_id
    )

    # Агенты
    for i in range(1, Config.AGENT_COUNT + 1):
        agent_name = f"agent-{i}"
        vms[agent_name] = create_vm_interactive(
            agent_name, 2, 2, 10, subnet_id, sg_id
        )

    Logger.info("Ожидание запуска ВМ (60 секунд)...")
    time.sleep(60)

    Logger.success("Все ВМ запущены ✅")
    return vms

# =============================================================================
# НАСТРОЙКА ZABBIX
# =============================================================================

def configure_zabbix_server_interactive(server_info: dict):
    """Настройка Zabbix Server с подтверждением."""
    Logger.step("НАСТРОЙКА ZABBIX SERVER")

    if not ask_confirmation(f"Настроить Zabbix Server на {server_info['public_ip']}"):
        Logger.warning("Пропущено по выбору пользователя")
        return False

    public_ip = server_info['public_ip']

    # Скрипт настройки (сокращённая версия)
    script = f"""#!/bin/bash
set -e
DB_NAME="{Config.DB_NAME}"
DB_USER="{Config.DB_USER}"
DB_PASS="{Config.DB_PASS}"

echo "🔧 Начало настройки Zabbix Server..."

# Репозиторий
echo "deb https://repo.zabbix.com/zabbix/6.0/ubuntu jammy main" > /etc/apt/sources.list.d/zabbix.list
curl -fsSL https://repo.zabbix.com/zabbix-official-repo.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/zabbix-official-repo.gpg
apt update

# Пакеты
apt install zabbix-server-pgsql zabbix-frontend-php zabbix-apache-conf zabbix-agent2 postgresql postgresql-contrib curl wget -y

# БД
su - postgres -c "psql -c \\"DROP USER IF EXISTS $DB_USER CASCADE;\\"" 2>/dev/null || true
su - postgres -c "psql -c \\"DROP DATABASE IF EXISTS $DB_NAME;\\"" 2>/dev/null || true
su - postgres -c "psql -c \\"CREATE USER $DB_USER WITH PASSWORD '$DB_PASS';\\""
su - postgres -c "psql -c \\"CREATE DATABASE $DB_NAME OWNER $DB_USER;\\""

# Схема
cd /tmp
wget -q https://cdn.zabbix.com/zabbix/sources/stable/6.0/zabbix-6.0.45.tar.gz
tar -xzf zabbix-6.0.45.tar.gz
cd zabbix-6.0.45/database/postgresql
su - $DB_USER -c "psql $DB_NAME < schema.sql"
su - $DB_USER -c "psql $DB_NAME < images.sql"
su - $DB_USER -c "psql $DB_NAME < data.sql"

# Конфиг
sed -i 's/# DBPassword=/DBPassword=$DB_PASS/' /etc/zabbix/zabbix_server.conf

# PHP
apt install php8.1-fpm libapache2-mod-php8.1 php8.1-pgsql php8.1-gd php8.1-mbstring php8.1-xml php8.1-bcmath php8.1-curl -y
a2enmod proxy_fcgi setenvif rewrite alias
a2enconf zabbix php8.1-fpm
a2dissite 000-default.conf 2>/dev/null || true
sed -i 's/post_max_size = .*/post_max_size = 16M/' /etc/php/8.1/fpm/php.ini
sed -i 's/max_execution_time = .*/max_execution_time = 300/' /etc/php/8.1/fpm/php.ini
sed -i 's/max_input_time = .*/max_input_time = 300/' /etc/php/8.1/fpm/php.ini
sed -i 's/# php_value date.timezone.*/php_value date.timezone Europe\\/Moscow/' /etc/apache2/conf-enabled/zabbix.conf
chown -R www-www-data /usr/share/zabbix

# Перезапуск
systemctl daemon-reload
systemctl restart zabbix-server zabbix-agent2 apache2 php8.1-fpm
systemctl enable zabbix-server zabbix-agent2 apache2 php8.1-fpm

echo "✅ Zabbix Server настроен!"
"""

    # Сохраняем скрипт
    script_path = "/tmp/zabbix-server-interactive.sh"
    with open(script_path, 'w') as f:
        f.write(script)
    os.chmod(script_path, 0o755)

    # Копируем и выполняем
    Logger.info("Копирование скрипта на сервер...")
    subprocess.run(f"scp -i {Config.SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no {script_path} yc-user@{public_ip}:/tmp/", shell=True)

    Logger.info("Выполнение настройки (5-10 минут)...")
    subprocess.run(f"ssh -i {Config.SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no yc-user@{public_ip} 'sudo bash /tmp/zabbix-server-interactive.sh'", shell=True)

    Logger.success("Zabbix Server настроен ✅")
    return True

def configure_agents_interactive(vms: dict, server_internal_ip: str):
    """Настройка агентов с подтверждением."""
    Logger.step("НАСТРОЙКА ZABBIX AGENTS")

    for i in range(1, Config.AGENT_COUNT + 1):
        agent_name = f"agent-{i}"
        agent_info = vms[agent_name]

        if not ask_confirmation(f"Настроить {agent_name} ({agent_info['public_ip']})"):
            Logger.warning("Пропущено по выбору пользователя")
            continue

        public_ip = agent_info['public_ip']

        script = f"""#!/bin/bash
set -e
SERVER_IP="{server_internal_ip}"
HOSTNAME="{agent_name}"

echo "deb https://repo.zabbix.com/zabbix/6.0/ubuntu jammy main" > /etc/apt/sources.list.d/zabbix.list
curl -fsSL https://repo.zabbix.com/zabbix-official-repo.key | gpg --dearmor -o /etc/apt/trusted.gpg.d/zabbix-official-repo.gpg
apt update
apt install zabbix-agent2 -y

sed -i "s/Server=127.0.0.1/Server=$SERVER_IP/" /etc/zabbix/zabbix_agent2.conf
sed -i "s/ServerActive=127.0.0.1/ServerActive=$SERVER_IP/" /etc/zabbix/zabbix_agent2.conf
sed -i "s/Hostname=Zabbix server/Hostname=$HOSTNAME/" /etc/zabbix/zabbix_agent2.conf

systemctl restart zabbix-agent2
systemctl enable zabbix-agent2

echo "✅ {agent_name} настроен!"
"""

        script_path = f"/tmp/zabbix-agent-{agent_name}.sh"
        with open(script_path, 'w') as f:
            f.write(script)
        os.chmod(script_path, 0o755)

        subprocess.run(f"scp -i {Config.SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no {script_path} yc-user@{public_ip}:/tmp/", shell=True)
        subprocess.run(f"ssh -i {Config.SSH_PRIVATE_KEY} -o StrictHostKeyChecking=no yc-user@{public_ip} 'sudo bash /tmp/zabbix-agent-{agent_name}.sh'", shell=True)

        Logger.success(f"{agent_name} настроен ✅")

# =============================================================================
# ИТОГОВЫЙ ОТЧЁТ
# =============================================================================

def print_summary_interactive(vms: dict):
    """Вывод итоговой информации."""
    server_info = vms[Config.SERVER_NAME]

    print(f"""
{Colors.CYAN}{'='*70}{Colors.NC}
{Colors.GREEN}              🎉 РАЗВЁРТЫВАНИЕ ЗАВЕРШЕНО! 🎉{Colors.NC}
{Colors.CYAN}{'='*70}{Colors.NC}

{Colors.CYAN}📊 ZABBIX WEB-ИНТЕРФЕЙС:{Colors.NC}
   URL:      {Colors.YELLOW}http://{server_info['public_ip']}/zabbix{Colors.NC}
   Логин:    {Colors.YELLOW}Admin{Colors.NC}
   Пароль:   {Colors.YELLOW}{Config.DB_PASS}{Colors.NC}

{Colors.CYAN}🖥️ ВИРТУАЛЬНЫЕ МАШИНЫ:{Colors.NC}
""")

    for name, info in vms.items():
        print(f"   {Colors.GREEN}✓{Colors.NC} {name:20} Internal: {info['internal_ip']:15} Public: {info['public_ip']}")

    print(f"""
{Colors.CYAN}📋 СЛЕДУЮЩИЕ ШАГИ:{Colors.NC}
   1. Откройте http://{server_info['public_ip']}/zabbix
   2. Пройдите мастер установки (PostgreSQL, порт 5432)
   3. Добавьте хосты agent-1 и agent-2 в Configuration → Hosts
   4. Сделайте скриншоты для отчёта

{Colors.CYAN}{'='*70}{Colors.NC}
""")

# =============================================================================
# ГЛАВНАЯ ФУНКЦИЯ
# =============================================================================

def main_interactive():
    """Интерактивный режим развёртывания."""
    print(f"""
{Colors.CYAN}{'='*70}{Colors.NC}
{Colors.CYAN}    ZABBIX 6.0 LTS - ИНТЕРАКТИВНОЕ РАЗВЁРТЫВАНИЕ{Colors.NC}
{Colors.CYAN}{'='*70}{Colors.NC}
""")

    # Проверка условий
    check_prerequisites_interactive()

    # Сеть
    Logger.step("СЕТЕВАЯ ИНФРАСТРУКТУРА")
    network_id = create_network_interactive()
    subnet_id = create_subnet_interactive(network_id)
    sg_id = create_security_group_interactive()

    # ВМ
    vms = create_all_vms_interactive(subnet_id, sg_id)

    # Настройка Zabbix
    configure_zabbix_server_interactive(vms[Config.SERVER_NAME])
    configure_agents_interactive(vms, vms[Config.SERVER_NAME]['internal_ip'])

    # Итог
    print_summary_interactive(vms)

if __name__ == "__main__":
    main_interactive()