; Compile with ISCC /DAppVersion=2.1.0 installer\Spyder.iss
; AppId and AppMutex must remain stable across every release.
#ifndef AppVersion
  #error AppVersion must be supplied by build.py
#endif
#define Root ".."

[Setup]
AppId=Spyder.Desktop
AppName=Spyder
AppVersion={#AppVersion}
AppPublisher=goujandev
AppPublisherURL=https://github.com/goujandev/spyder
AppSupportURL=https://github.com/goujandev/spyder/issues
AppUpdatesURL=https://github.com/goujandev/spyder/releases
DefaultDirName={localappdata}\Programs\Spyder
DefaultGroupName=Spyder
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#Root}\LICENSE
SetupIconFile={#Root}\assets\Spyder.ico
UninstallDisplayIcon={app}\Spyder.exe
UninstallDisplayName=Spyder
OutputDir={#Root}\dist
OutputBaseFilename=Spyder-Setup-{#AppVersion}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
AppMutex=Local\Spyder.App
CloseApplications=no
RestartApplications=no
UsePreviousAppDir=yes
UsePreviousTasks=yes

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#Root}\dist\Spyder\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#Root}\LICENSE"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#Root}\THIRD-PARTY-NOTICES.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "installed.ini"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Spyder"; Filename: "{app}\Spyder.exe"; AppUserModelID: "Spyder.App"
Name: "{autodesktop}\Spyder"; Filename: "{app}\Spyder.exe"; Tasks: desktopicon; AppUserModelID: "Spyder.App"

[Run]
Filename: "{app}\Spyder.exe"; Description: "Launch Spyder"; Flags: nowait postinstall skipifsilent
Filename: "{app}\Spyder.exe"; Flags: nowait skipifnotsilent; Check: IsAppUpdate

[Code]
function OpenProcess(Access: LongWord; InheritHandle: Boolean; ProcessId: LongWord): THandle;
  external 'OpenProcess@kernel32.dll stdcall';
function WaitForSingleObject(Handle: THandle; Milliseconds: LongWord): LongWord;
  external 'WaitForSingleObject@kernel32.dll stdcall';
function CloseHandle(Handle: THandle): Boolean;
  external 'CloseHandle@kernel32.dll stdcall';

function IsAppUpdate: Boolean;
begin
  Result := ExpandConstant('{param:UPDATE|0}') = '1';
end;

function InitializeSetup: Boolean;
var
  ParentPID: Integer;
  ParentHandle: THandle;
  WaitResult: LongWord;
begin
  Result := True;
  if not IsAppUpdate then
    Exit;
  ParentPID := StrToIntDef(ExpandConstant('{param:PARENTPID|0}'), 0);
  if ParentPID <= 0 then
  begin
    MsgBox('The update did not include a valid Spyder process ID. Run setup manually.', mbError, MB_OK);
    Result := False;
    Exit;
  end;
  ParentHandle := OpenProcess($00100000, False, ParentPID);
  { A missing handle usually means the app has already exited. AppMutex is
    still checked by Setup before replacing any files. }
  if ParentHandle <> 0 then
  begin
    WaitResult := WaitForSingleObject(ParentHandle, 30000);
    CloseHandle(ParentHandle);
    if WaitResult <> 0 then
    begin
      MsgBox('Spyder did not close in time. Close Spyder and run setup again.', mbError, MB_OK);
      Result := False;
    end;
  end;
end;
