# Source Snapshot: app/data_access.py

- Source: `C:\Users\azzib\Desktop\ComfyUI\StyleLab\Anima-Style-Lab-2.0\app\data_access.py`
- Original Byte SHA-256: `05edc5541e134ebcabfcce1d3f81366e369453a5d778f38555db85b650fb89e6`
- Snapshot Text SHA-256: `05edc5541e134ebcabfcce1d3f81366e369453a5d778f38555db85b650fb89e6`
- 형식: UTF-8 / LF / 마지막 줄바꿈. Markdown 외곽을 제외한 코드 블록 내용이 Snapshot입니다.
- 범위: 전체 텍스트 파일
- 복원 시 생성 이미지·모델·인증 정보는 별도 준비합니다.

```python
"""Desktop과 웹 서버가 같은 데이터 폴더를 동시에 열지 못하게 합니다."""

import ctypes
import hashlib
from pathlib import Path


class DataDirectoryInUseError(RuntimeError):
    """다른 Style Lab 프로세스가 데이터를 사용하고 있음을 나타냅니다."""


class DataDirectoryLock:
    """데이터 폴더 경로로 구분되는 Windows Mutex를 실행 동안 보유합니다."""

    def __init__(self, data_directory):
        """폴더 이름이 같아도 실제 경로가 다르면 별도의 Mutex를 준비합니다."""
        normalized_path = str(Path(data_directory).resolve()).casefold()
        directory_digest = hashlib.sha256(normalized_path.encode('utf-8')).hexdigest()[:32]
        self.mutex_name = f'Local\\StyleLabDataDirectory-{directory_digest}'
        self.mutex_handle = None
        self.kernel_library = ctypes.WinDLL('kernel32', use_last_error=True)
        self.kernel_library.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_bool, ctypes.c_wchar_p]
        self.kernel_library.CreateMutexW.restype = ctypes.c_void_p
        self.kernel_library.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        self.kernel_library.WaitForSingleObject.restype = ctypes.c_uint32
        self.kernel_library.ReleaseMutex.argtypes = [ctypes.c_void_p]
        self.kernel_library.CloseHandle.argtypes = [ctypes.c_void_p]

    def __enter__(self):
        """대기하지 않고 잠금을 획득하며, 사용 중이면 시작을 거부합니다."""
        mutex_handle = self.kernel_library.CreateMutexW(None, False, self.mutex_name)
        if not mutex_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        wait_result = self.kernel_library.WaitForSingleObject(mutex_handle, 0)
        if wait_result not in (0, 0x80):
            self.kernel_library.CloseHandle(mutex_handle)
            raise DataDirectoryInUseError('같은 데이터를 사용하는 Style Lab이 실행 중입니다. Desktop 앱 또는 웹 서버를 먼저 종료해 주세요.')
        self.mutex_handle = mutex_handle
        return self

    def __exit__(self, exception_type, exception_value, traceback):
        """실행이 정상 종료되거나 예외가 나도 Mutex Handle을 반납합니다."""
        if self.mutex_handle:
            self.kernel_library.ReleaseMutex(self.mutex_handle)
            self.kernel_library.CloseHandle(self.mutex_handle)
            self.mutex_handle = None
```
