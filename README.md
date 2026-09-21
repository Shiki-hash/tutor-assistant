# 助教答疑助手

面向助教的人工审核式答疑原型。使用 CrewAI 单 Agent 和 DeepSeek API，生成回复草稿、引用和核查事项；助教编辑后确认，保留历史与问题续办记录。

## 快速开始

建议 Python 3.12。在仓库根目录执行（Windows PowerShell）：

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
Copy-Item .env.example .env
# 在本机 .env 填入自己的密钥
.venv\Scripts\python server.py
```

打开 http://127.0.0.1:8765 。模型可用性以服务商账户为准，可在 .env 修改模型名。调用真实模型会产生费用，密钥只保存在本机。

## 验证

```powershell
.venv\Scripts\python -m unittest discover -s tests
```

测试默认使用模拟客户端，不消耗模型额度。运行产生的数据不纳入Git版本控制。

## 产品与技术范围

本项目是可运行的本地单用户原型，展示需求定义、界面/API/存储落地、证据核查和评估迭代。未实现生产级认证或公网部署，请勿直接暴露公网。

公开仓库只包含演示代码及合成案例，不包含学生记录、公司内部资料、实际人工评分、密钥或私人运行数据库。演示规则不代表公司正式政策；未将合成验收宣称为真实业务提升。

## 演示建议

先运行离线或固定演示流程，再按需配置API。查看原始输入、生成结果、引用依据和人工确认边界。失败记录与缺失证据不应被当成成功或零成本。

## 开发方式

使用AI编程工具辅助实现，围绕产品需求进行功能拆解、运行核查与迭代。仅发布原创原型代码，没有复制未获授权的第三方项目代码。
