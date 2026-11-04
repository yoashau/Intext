#define AppVersion "0.2.0"

[Setup]
AppId={{A7C3E4B1-6D28-4F0A-9B55-1E2F4A8C0D11}
AppName=Intext
AppVersion={#AppVersion}
AppPublisher=Intext
SourceDir=..
DefaultDirName={localappdata}\Programs\Intext
DefaultGroupName=Intext
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Intext-Setup
SetupIconFile=src\intext\assets\intext.ico
UninstallDisplayIcon={app}\Intext.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=no
RestartApplications=no

[Files]
Source: "dist\Intext\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Intext"; Filename: "{app}\Intext.exe"

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueName: "Intext"; Flags: dontcreatekey uninsdeletevalue

[Run]
Filename: "{app}\Intext.exe"; Description: "启动 Intext"; Flags: nowait postinstall skipifsilent

[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  Locator, Service, Processes, Process: Variant;
  QueryPath, Query: String;
  Attempt, I, Code, PID: Integer;
begin
  Result := '';
  QueryPath := ExpandConstant('{app}\Intext.exe');
  StringChangeEx(QueryPath, '\', '\\', True);
  StringChangeEx(QueryPath, '''', '\''', True);
  Query := 'SELECT * FROM Win32_Process WHERE Name = ''Intext.exe'' AND ExecutablePath = ''' + QueryPath + '''';
  try
    Locator := CreateOleObject('WbemScripting.SWbemLocator');
    Service := Locator.ConnectServer('', 'root\CIMV2');
    { Only close the executable in this installation directory. }
    for Attempt := 0 to 50 do
    begin
      Processes := Service.ExecQuery(Query);
      if Processes.Count = 0 then Exit;
      for I := 0 to Processes.Count - 1 do
      begin
        Process := Processes.ItemIndex(I);
        PID := Process.ProcessId;
        Code := Process.Terminate(0);
        Log(Format('Closing Intext PID %d before upgrade (result %d)', [PID, Code]));
      end;
      Sleep(100);
    end;
    Result := '无法退出正在运行的 Intext，尚未替换程序文件。';
  except
    Log(GetExceptionMessage);
    Result := '无法检查正在运行的 Intext，尚未替换程序文件。';
  end;
end;
