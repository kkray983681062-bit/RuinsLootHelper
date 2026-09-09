"""Keep cyclic Tcl/Tk finalizers on the UI thread, never a reader thread."""
import gc
import threading


def guard_tk(root):
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError('Tk lifecycle must be initialized on the UI thread')
    # Reference counting is unchanged. Only cyclic collection is scheduled here:
    # Tcl interpreters and image/variable finalizers are thread-affine.
    gc.disable()
    if hasattr(root, '_ruins_gc_job'):
        return
    gc.collect()
    root._ruins_gc_job = None

    def sweep():
        root._ruins_gc_job = None
        gc.collect()
        root._ruins_gc_job = root.after(2000, sweep)

    def destroy(event):
        if event.widget == root and root._ruins_gc_job:
            root.after_cancel(root._ruins_gc_job)
            root._ruins_gc_job = None

    root.bind('<Destroy>', destroy, add='+')
    root._ruins_gc_job = root.after(2000, sweep)
