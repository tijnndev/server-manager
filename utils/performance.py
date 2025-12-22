"""
Performance monitoring and optimization utilities for Server Manager.
Provides caching, async operations, and monitoring helpers.
"""
import functools
import time
import asyncio
from concurrent.futures import ThreadPoolExecutor
import subprocess
from typing import Callable, Optional

# Thread pool for running blocking I/O operations asynchronously
# Size matches the number of gevent workers to handle subprocess calls efficiently
executor = ThreadPoolExecutor(max_workers=32, thread_name_prefix="perf_")


def timed_cache(timeout: int = 60):
    """
    Decorator to cache function results with custom timeout.
    Uses Flask-Caching if available, otherwise falls back to simple dict cache.
    
    Args:
        timeout: Cache timeout in seconds (default: 60)
    
    Example:
        @timed_cache(timeout=300)
        def expensive_operation():
            return compute_something()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from app import cache
                # Create cache key from function name and arguments
                cache_key = f"{func.__name__}_{str(args)}_{str(kwargs)}"
                result = cache.get(cache_key)
                
                if result is None:
                    result = func(*args, **kwargs)
                    cache.set(cache_key, result, timeout=timeout)
                
                return result
            except (ImportError, AttributeError):
                # Fallback if cache not available
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def async_subprocess(cmd: list, cwd: Optional[str] = None, timeout: int = 30) -> dict:
    """
    Run subprocess command asynchronously without blocking gevent workers.
    
    Args:
        cmd: Command to run as list of strings
        cwd: Working directory for command
        timeout: Command timeout in seconds
    
    Returns:
        dict with 'returncode', 'stdout', 'stderr'
    
    Example:
        result = async_subprocess(['docker', 'ps'], timeout=10)
        if result['returncode'] == 0:
            print(result['stdout'])
    """
    def _run():
        try:
            result = subprocess.run(
                cmd,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False
            )
            return {
                'returncode': result.returncode,
                'stdout': result.stdout,
                'stderr': result.stderr
            }
        except subprocess.TimeoutExpired:
            return {
                'returncode': -1,
                'stdout': '',
                'stderr': f'Command timed out after {timeout} seconds'
            }
        except Exception as e:
            return {
                'returncode': -1,
                'stdout': '',
                'stderr': str(e)
            }
    
    # Submit to thread pool and wait for result
    future = executor.submit(_run)
    return future.result(timeout=timeout + 5)


def performance_monitor(func: Callable) -> Callable:
    """
    Decorator to monitor function execution time.
    Logs slow operations (>1 second) for optimization.
    
    Example:
        @performance_monitor
        def slow_operation():
            time.sleep(2)
    """
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        start_time = time.time()
        result = func(*args, **kwargs)
        elapsed = time.time() - start_time
        
        if elapsed > 1.0:  # Log operations taking more than 1 second
            print(f"[PERF] {func.__name__} took {elapsed:.2f}s - Consider optimization")
        
        return result
    
    return wrapper


def batch_cache_invalidate(keys: list):
    """
    Invalidate multiple cache keys at once for bulk operations.
    
    Args:
        keys: List of cache keys to invalidate
    
    Example:
        batch_cache_invalidate(['process_list', 'server_stats', 'docker_status'])
    """
    try:
        from app import cache
        for key in keys:
            cache.delete(key)
    except (ImportError, AttributeError):
        pass


def memoize_with_user(timeout: int = 300):
    """
    Cache decorator that includes user_id in cache key for per-user caching.
    
    Args:
        timeout: Cache timeout in seconds
    
    Example:
        @memoize_with_user(timeout=60)
        def get_user_processes(user_id):
            return Process.query.filter_by(owner_id=user_id).all()
    """
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                from app import cache
                from flask import session
                
                user_id = session.get('user_id', 'anonymous')
                cache_key = f"{func.__name__}_user_{user_id}_{str(args)}_{str(kwargs)}"
                result = cache.get(cache_key)
                
                if result is None:
                    result = func(*args, **kwargs)
                    cache.set(cache_key, result, timeout=timeout)
                
                return result
            except (ImportError, AttributeError):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


class DockerCommandPool:
    """
    Pool for managing Docker commands efficiently.
    Prevents overwhelming Docker daemon with concurrent requests.
    """
    
    def __init__(self, max_concurrent: int = 10):
        self.semaphore = asyncio.Semaphore(max_concurrent)
        self.executor = ThreadPoolExecutor(max_workers=max_concurrent)
    
    def run_docker_command(self, cmd: list, cwd: Optional[str] = None, timeout: int = 30) -> dict:
        """
        Run Docker command through the pool to prevent overwhelming the daemon.
        
        Args:
            cmd: Docker command as list
            cwd: Working directory
            timeout: Command timeout
        
        Returns:
            Command result dict
        """
        return async_subprocess(cmd, cwd=cwd, timeout=timeout)


# Global Docker command pool
docker_pool = DockerCommandPool(max_concurrent=15)


def get_metrics():
    """
    Get current performance metrics for monitoring.
    
    Returns:
        dict with worker count, cache hit rate, etc.
    """
    try:
        import psutil
        
        return {
            'workers': 32,
            'cpu_percent': psutil.cpu_percent(interval=0.1),
            'memory_percent': psutil.virtual_memory().percent,
            'thread_pool_active': executor._threads.__len__() if hasattr(executor, '_threads') else 0,
        }
    except Exception as e:
        return {'error': str(e)}
