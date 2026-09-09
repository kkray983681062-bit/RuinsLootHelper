# Windows 打包

使用项目根目录的 `requirements-dev.txt` 准备环境，运行：

```powershell
python -B packaging/build_release.py
```

详细命令、产物位置、版本维护与验证要求见 [开发说明](../docs/development.md)。本脚本只在本地构建，不创建 GitHub Release 或上传蓝奏云。
