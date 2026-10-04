"""Build/run the local prototype with its private .NET toolchain."""
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DOTNET = ROOT / '.toolchain/dotnet/dotnet'
DLL = ROOT / 'WitcherRevival.Server/bin/Release/net10.0/WitcherRevival.Server.dll'

def environment():
    env = os.environ.copy()
    env.update(DOTNET_ROOT=str(DOTNET.parent), DOTNET_CLI_HOME=str(ROOT / '.cache/dotnet'),
               DOTNET_CLI_TELEMETRY_OPTOUT='1', DOTNET_SKIP_FIRST_TIME_EXPERIENCE='1',
               DOTNET_GENERATE_ASPNET_CERTIFICATE='false', MSBuildEnableWorkloadResolver='false',
               NUGET_PACKAGES=str(ROOT / '.cache/nuget'), ASPNETCORE_ENVIRONMENT='Production')
    return env

if __name__ == '__main__':
    action, *args = sys.argv[1:] or ['build']
    if not DOTNET.exists():
        raise SystemExit('Run python install_toolchain.py first.')
    if action == 'build':
        command = [str(DOTNET), 'build', 'WitcherRevival.Server/WitcherRevival.Server.csproj', '--configuration', 'Release',
                   '-p:NuGetAudit=false', '-p:UseSharedCompilation=false', *args]
    elif action == 'run':
        command = [str(DOTNET), str(DLL), *args]
    elif action == 'test':
        command = [sys.executable, '-m', 'unittest', 'discover', '-s', 'tests', '-v', *args]
    else:
        raise SystemExit('Usage: python dev.py build|run|test [arguments]')
    raise SystemExit(subprocess.call(command, cwd=ROOT, env=environment()))
