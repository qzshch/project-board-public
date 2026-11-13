"""Process containment for one approved test command, including grandchildren."""
import ctypes
import os
import signal
import subprocess
import psutil
import sys
import time


class CommandGroup:
    def __init__(self):self.job=None;self.process=None;self.closed=False;self.created=None

    def launch(self,argv,**kwargs):
        if os.name!='nt':
            if sys.platform.startswith('linux'):
                # Reparent orphaned grandchildren here so timeout/cancellation
                # does not leave zombies for a container's non-reaping PID 1.
                if ctypes.CDLL(None,use_errno=True).prctl(36,1,0,0,0)!=0:raise RuntimeError('Cannot contain/reap Linux test descendants')
            self.process=subprocess.Popen(argv,start_new_session=True,**kwargs);self.created=psutil.Process(self.process.pid).create_time();return self.process
        from ctypes import wintypes as w
        k=ctypes.WinDLL('kernel32',use_last_error=True)
        class BASIC(ctypes.Structure):
            _fields_=[('ProcessTime',ctypes.c_longlong),('JobTime',ctypes.c_longlong),('LimitFlags',w.DWORD),('MinWorkingSet',ctypes.c_size_t),('MaxWorkingSet',ctypes.c_size_t),('ActiveProcessLimit',w.DWORD),('Affinity',ctypes.c_size_t),('PriorityClass',w.DWORD),('SchedulingClass',w.DWORD)]
        class IO(ctypes.Structure):_fields_=[(n,ctypes.c_ulonglong) for n in ('ReadOps','WriteOps','OtherOps','ReadBytes','WriteBytes','OtherBytes')]
        class EXT(ctypes.Structure):_fields_=[('Basic',BASIC),('Io',IO),('ProcessMemoryLimit',ctypes.c_size_t),('JobMemoryLimit',ctypes.c_size_t),('PeakProcessMemoryUsed',ctypes.c_size_t),('PeakJobMemoryUsed',ctypes.c_size_t)]
        k.CreateJobObjectW.restype=w.HANDLE;k.CreateJobObjectW.argtypes=[ctypes.c_void_p,w.LPCWSTR]
        k.SetInformationJobObject.argtypes=[w.HANDLE,ctypes.c_int,ctypes.c_void_p,w.DWORD]
        k.AssignProcessToJobObject.argtypes=[w.HANDLE,w.HANDLE];k.CloseHandle.argtypes=[w.HANDLE]
        job=k.CreateJobObjectW(None,None)
        if not job:raise ctypes.WinError(ctypes.get_last_error())
        limit=EXT();limit.Basic.LimitFlags=0x2000 # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        if not k.SetInformationJobObject(job,9,ctypes.byref(limit),ctypes.sizeof(limit)):k.CloseHandle(job);raise ctypes.WinError(ctypes.get_last_error())
        self.job=job;self.kernel=k
        try:
            kwargs['creationflags']=kwargs.get('creationflags',0)|0x4 # suspended until contained
            self.process=subprocess.Popen(argv,**kwargs)
            self.created=psutil.Process(self.process.pid).create_time()
            if not k.AssignProcessToJobObject(job,w.HANDLE(int(self.process._handle))):raise ctypes.WinError(ctypes.get_last_error())
            n=ctypes.WinDLL('ntdll');n.NtResumeProcess.argtypes=[w.HANDLE];n.NtResumeProcess.restype=ctypes.c_long
            if n.NtResumeProcess(w.HANDLE(int(self.process._handle)))!=0:raise RuntimeError('Cannot resume contained command')
            return self.process
        except BaseException:
            if self.process is not None and self.process.poll() is None:self.process.kill();self.process.wait(5)
            self.close();raise

    def close(self):
        if self.closed:return
        self.closed=True
        if self.job is not None:self.kernel.CloseHandle(self.job);self.job=None
        elif os.name!='nt' and self.process is not None:
            try:os.killpg(self.process.pid,signal.SIGKILL)
            except ProcessLookupError:pass
        if self.process is not None:
            try:self.process.wait(5)
            except subprocess.TimeoutExpired:self.process.kill();self.process.wait(5)
            if sys.platform.startswith('linux'):
                for _ in range(100):
                    try:
                        pid,_=os.waitpid(-self.process.pid,os.WNOHANG)
                        if pid==0:time.sleep(.01)
                    except ChildProcessError:break
