# server生产部署

正式根目录 /srv/project-board；source为releases/nas-20261113/source，state单独持久化。此处unit是现场已运行版本。用户example-owner的systemd用户服务已enable，Linger=yes；无需PC常驻。

server Python 3.11隔离环境位于根目录.venv，安装本目录锁定的psutil版本。本机server缺少ensurepip，已将官方manylinux ABI3 wheel经G盘任务目录下载、SHA验证后解压安装到该venv的site-packages；未更改系统Python。部署证据有wheel-download.log。后续更新先在独立非C盘状态/端口验收，停止服务后一致性备份，切换source并重启读回。

将unit放在server根deploy目录，链接到~/.config/systemd/user/project-board.service，然后systemctl --user daemon-reload与enable --now。Tailscale在既有server tailscale容器内运行，仅配置server HTTP18785到127.0.0.1:24710，禁止serve reset，不更改其他应用的转发。

源码/配置不包含凭据。state/_private中的身份和operator.html只通过授权私有通道交付。PC旧state只保留迁移指针，不能再次初始化/启动；原身份只更新url至server，不重签为全局管理者。
