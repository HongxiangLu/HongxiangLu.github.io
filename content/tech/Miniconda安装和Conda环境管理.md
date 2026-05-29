---
title: "Miniconda安装和Conda环境管理"
date: 2026-05-29T12:00:00+08:00
slug: conda
draft: false
categories:
    - "技术"
---

## 第一阶段：Miniconda 的初始安装与系统配置

**1. 安装时的"两不勾选"**
* **不勾选** "Add Miniconda3 to my PATH environment variable"：避免安装程序破坏现有的系统环境变量结构。
* **不勾选** "Register Miniconda3 as the system Python"：坚决防止外部软件将 Miniconda 的 `base` 环境当成系统的全局默认 Python，从而从根源上杜绝环境污染。

**2. 手动接管系统环境变量**
* 安装完成后，手动将 Miniconda 的三个核心路径（根目录、`Scripts` 目录、`Library\bin` 目录）添加到 Windows 系统的 `Path` 环境变量中。

**3. 解除 PowerShell 的封印**
* 以管理员身份打开 PowerShell，执行 `Set-ExecutionPolicy RemoteSigned -Scope CurrentUser`，允许运行本地脚本。
* 接着执行 `conda init powershell`，让终端完美接管并显示 Conda 的环境前缀。

## 第二阶段：防渗透与目录隔离（系统整洁的核心）

**1. 夺回核心目录的读写控制权**
如果 Miniconda 安装在受保护的 C 盘路径，日常以普通用户身份创建环境或安装包时会被拦截，导致 Conda 偷偷将文件写回 `C:\Users\[用户名]\.conda`。这有两个破局方案：
* **提权法**：在文件夹属性中，赋予当前 Windows 账户对 Miniconda 安装目录的"完全控制"权限。
* **重定向法）**：通过执行 `conda config --add envs_dirs` 和 `conda config --add pkgs_dirs`，将虚拟环境和包下载缓存彻底转移到独立的数据盘。

**2. 预建缓存目录**
* 在执行路径重定向前，建议手动在目标位置建好 `pkgs`（包缓存）文件夹并确认读写权限，防止首次下载时因权限突发问题导致重定向失败。

## 第三阶段：虚拟环境的创建与精细化管理

**1. 永远显式指定 Python**
* `conda create -n env_name` 默认只建空壳，**不包含** Python 解释器。
* 必须养成加上 `python` 或具体版本号（如 `python=3.11`）的习惯。否则，在这个环境里使用 `pip` 或启动本地代理服务时，会直接"穿透"调用外部的全局 Python，彻底使得环境隔离失效。

**2. 强制每个环境自带 pip**
* 执行 `conda config --add create_default_packages pip`，之后每次 `conda create` 都会自动在新环境中安装独立的 pip。
* 这能从根源上杜绝"子环境没有 pip → 穿透调用 base 的 pip → 包装错环境"的经典事故。
* 若偶尔需要创建不含 Python 的纯净环境（如只装 Node.js），可在创建时加 `--no-default-packages` 跳过。

**3. 核心依赖"一波流"安装**
* 在创建环境时，尽量把确定的核心大包（如 `fastapi`、`requests` 等）与 Python 版本写在同一行命令里（例如 `conda create -n env_name python=3.11 fastapi requests`）。
* 这样能触发 Conda 强大的全局依赖解析器，计算出最完美的兼容版本树，极大地降低后续遇到 C/C++ 底层冲突的概率。
