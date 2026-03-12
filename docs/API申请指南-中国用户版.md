# API Key 申请指南（中国用户版）

> 更新时间：2026年3月
> 适用对象：仅拥有中国手机号和账户的用户

---

## 一、阿里云百炼 API Key

### 1.1 服务简介

阿里云百炼是基于通义千问大模型的一站式 AI 开发平台，本项目使用其 API 进行论文内容智能分析。

### 1.2 申请流程

**前提条件：**
- 阿里云账号（需实名认证）
- 支付宝或银行卡（用于账户充值，最低充值 1 元即可）

**步骤：**

1. **访问百炼平台**
   ```
   https://bailian.console.aliyun.com/
   ```

2. **登录阿里云账号**
   - 使用阿里云账号登录
   - 如无账号，需先注册并完成实名认证

3. **开通百炼服务**
   - 首次进入会提示开通服务
   - 点击"立即开通"

4. **充值账户**
   - 进入"费用中心"或点击右上角余额
   - 建议充值 1-10 元用于测试
   - 通义千问调用费用很低，1 元可调用数百次

5. **获取 API Key**
   - 点击左侧菜单"API-KEY 管理"
   - 点击"创建 API Key"
   - 复制生成的 API Key（格式类似：`sk-xxxxxxxxxxxxxx`）

6. **配置环境变量**
   ```bash
   export BAILIAN_API_KEY="sk-your-api-key-here"
   ```

### 1.3 费用说明

- 通义千问 qwen-plus 模型：约 0.004 元/千 tokens
- 分析一篇论文通常花费不到 0.1 元
- 新用户可能有免费额度，具体以官网为准

---

## 二、Tavily API Key

### 2.1 服务简介

Tavily 是专为 AI Agent 设计的搜索引擎 API，本项目用于在学术网站搜索相关文献。

### 2.2 申请流程

**前提条件：**
- 需要科学上网环境（仅注册时需要）
- 邮箱或 GitHub 账号

**步骤：**

1. **访问官网**
   ```
   https://tavily.com/
   或
   https://app.tavily.com/
   ```

2. **注册账号**
   - 点击 "Sign Up"
   - 可以使用邮箱注册，或直接用 GitHub 账号登录
   - 完成邮箱验证

3. **获取 API Key**
   - 登录后进入 Dashboard
   - 在首页即可看到 API Key
   - 或访问：`https://app.tavily.com/home`

4. **配置环境变量**
   ```bash
   export TAVILY_API_KEY="tvly-your-api-key-here"
   ```

### 2.3 免费额度

- **每月 1,000 次免费调用**
- 适合测试和轻度使用
- 无需绑定支付方式

---

## 三、配置说明

### 3.1 创建 .env 文件

在项目根目录创建 `.env` 文件：

```bash
# Tavily API Key（用于网络搜索）
TAVILY_API_KEY=tvly-your-api-key-here

# 阿里云百炼 API Key（用于论文分析）
BAILIAN_API_KEY=sk-your-api-key-here
```

### 3.2 验证配置

运行程序验证 API Key 是否配置正确：

```bash
python code/paper_reference_searcher.py
```

如果配置正确，程序会提示输入论文内容；如果配置错误，会提示相应的错误信息。

---

## 四、常见问题

### Q1: 阿里云百炼提示余额不足？

充值 1-10 元即可正常使用，通义千问调用费用很低。

### Q2: Tavily 注册需要国外手机号吗？

不需要，使用邮箱或 GitHub 账号即可注册。

### Q3: 两个 API Key 的调用顺序？

程序首先使用阿里云百炼分析论文内容，然后使用 Tavily 搜索相关文献。

---

*本文档持续更新，如有问题欢迎反馈*