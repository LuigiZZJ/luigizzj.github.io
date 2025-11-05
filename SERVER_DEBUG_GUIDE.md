# 服务器CPU高占用问题排查指南

## 问题症状
- SSH无法连接
- CPU使用率98%，内存1%
- 功率稳定在最低
- KVM界面有画面但无法操作

## 立即处理方案

### 1. 强制重启服务器
```bash
# 方法1: 通过BMC Web界面操作
# 登录BMC -> Power Control -> Power Reset

# 方法2: 使用ipmitool命令
ipmitool -H <BMC_IP> -U <USERNAME> -P <PASSWORD> power reset

# 方法3: 如果以上都不行，物理按电源键5秒强制关机
```

## 重启后立即执行的排查命令

### 1. 检查系统日志
```bash
# 查看系统崩溃前的日志
journalctl -xb -1 -p err
dmesg | tail -100
tail -200 /var/log/syslog
tail -200 /var/log/messages

# 检查是否有内核错误
grep -i "kernel panic\|segfault\|oom\|hung task" /var/log/kern.log
```

### 2. 查找CPU高占用进程
```bash
# 查看CPU占用top 10
ps aux --sort=-%cpu | head -11

# 实时监控
top -c
htop

# 检查是否有僵尸进程
ps aux | grep defunct
```

### 3. 检查系统负载和资源
```bash
# 查看系统负载
uptime
w

# 检查磁盘I/O
iostat -x 2 5
iotop

# 检查网络连接
netstat -antp | wc -l
ss -s
```

### 4. 检查定时任务
```bash
# 查看cron任务
crontab -l
cat /etc/crontab
ls -la /etc/cron.d/
ls -la /etc/cron.hourly/

# 检查systemd定时器
systemctl list-timers --all
```

### 5. 检查最近修改的文件
```bash
# 查找最近24小时修改的脚本
find /usr/local/bin /opt -type f -mtime -1 -ls
find /etc -type f -mtime -1 -ls
```

## 常见原因及解决方案

### 原因1: 失控的脚本或进程

**症状:** CPU高，内存低

**排查:**
```bash
# 找到高CPU进程
top -b -n 1 | head -20

# 查看进程详细信息
ps -ef | grep <PID>
lsof -p <PID>
strace -p <PID>
```

**解决:**
```bash
# 先尝试正常终止
kill <PID>

# 如果不行，强制终止
kill -9 <PID>

# 如果是服务，禁用它
systemctl stop <service>
systemctl disable <service>
```

### 原因2: 硬件中断风暴

**症状:** CPU被中断占用，/proc/interrupts增长快

**排查:**
```bash
# 查看中断统计
cat /proc/interrupts
watch -n 1 'cat /proc/interrupts | head -20'

# 检查软中断
mpstat -I SUM 2 5
```

**解决:**
- 检查是否有硬件故障（网卡、磁盘控制器）
- 更新驱动程序
- 临时禁用有问题的硬件

### 原因3: 磁盘I/O阻塞

**症状:** 高iowait，进程D状态

**排查:**
```bash
# 查看iowait
iostat -x 2 5

# 查看D状态进程（不可中断睡眠）
ps aux | awk '$8 ~ /D/ {print $0}'

# 检查磁盘健康
smartctl -a /dev/sda
dmesg | grep -i "I/O error\|disk error"
```

**解决:**
```bash
# 检查文件系统
fsck /dev/<device>

# 检查磁盘空间
df -h
df -i  # 检查inode是否用完

# 清理日志
journalctl --vacuum-time=7d
```

### 原因4: 死锁或内核bug

**症状:** 系统hang住，无响应

**排查:**
```bash
# 启用内核调试（需要重启前配置）
# 在 /etc/sysctl.conf 添加:
# kernel.panic = 10
# kernel.hung_task_timeout_secs = 120

# 查看内核hang任务
dmesg | grep "hung task"
```

**解决:**
- 更新内核到最新稳定版
- 回退到已知稳定的内核版本

## 预防措施

### 1. 设置监控告警
```bash
# 安装监控工具
apt-get install prometheus-node-exporter
# 或
yum install node_exporter

# 配置进程监控
systemctl enable node_exporter
systemctl start node_exporter
```

### 2. 配置资源限制
```bash
# 编辑 /etc/security/limits.conf
* soft nproc 65535
* hard nproc 65535
* soft nofile 65535
* hard nofile 65535

# 限制单个用户CPU使用
# 在 /etc/security/limits.conf
username hard cpu 60
```

### 3. 启用自动重启机制
```bash
# 在 /etc/sysctl.conf 添加
kernel.panic = 10  # panic后10秒自动重启
vm.panic_on_oom = 1  # OOM时触发panic

# 应用配置
sysctl -p
```

### 4. 设置看门狗
```bash
# 加载硬件看门狗模块
modprobe softdog
modprobe iTCO_wdt

# 安装watchdog服务
apt-get install watchdog
# 或
yum install watchdog

# 配置 /etc/watchdog.conf
watchdog-device = /dev/watchdog
max-load-1 = 24
min-memory = 1

# 启动服务
systemctl enable watchdog
systemctl start watchdog
```

### 5. 配置日志轮转
```bash
# 确保日志不会填满磁盘
# 编辑 /etc/logrotate.d/syslog
/var/log/syslog {
    daily
    rotate 7
    compress
    delaycompress
    missingok
    notifempty
}
```

## 应急检查清单

- [ ] 通过BMC重启服务器
- [ ] 检查系统日志 (journalctl, dmesg)
- [ ] 查看CPU占用top进程
- [ ] 检查磁盘空间和I/O
- [ ] 查看网络连接数
- [ ] 检查定时任务
- [ ] 查看最近修改的文件
- [ ] 检查硬件中断
- [ ] 更新系统和驱动
- [ ] 配置监控和告警

## 临时应急访问方法

如果SSH无法连接但系统还在运行:

1. **通过BMC的虚拟控制台(SOL)**
   ```bash
   ipmitool -H <BMC_IP> -U <USER> -P <PASS> sol activate
   ```

2. **通过KVM虚拟键盘**
   - 登录BMC Web界面
   - 启动虚拟KVM
   - 尝试 Ctrl+Alt+F1~F6 切换终端

3. **串口控制台**
   - 如果配置了串口，通过串口连接
