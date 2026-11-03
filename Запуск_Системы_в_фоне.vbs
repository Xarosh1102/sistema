Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "C:\Users\Azinem\Desktop\sistema"
WshShell.Run """C:\Users\Azinem\Desktop\sistema\venv\Scripts\pythonw.exe"" ""C:\Users\Azinem\Desktop\sistema\main.py""", 0, False
