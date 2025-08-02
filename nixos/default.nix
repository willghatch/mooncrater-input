{ python3Packages }:

python3Packages.buildPythonPackage {
  pname = "mooncrater-input";
  version = "0.1.0";
  src = ../.;

  pyproject = true;
  build-system = with python3Packages; [ setuptools wheel ];
  propagatedBuildInputs = with python3Packages; [ pyserial evdev ];
  doCheck = false;
}
