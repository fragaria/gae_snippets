__author__ = 'Robin Gottfried <czervenka@github.com>'

"""
Simple thread pool working on Google App Engine (tested on frontend).


Examples:
    # prints data which fits in queue
    # using 10 threads
    from thread_pool import ThreadPool
    from time import sleep

    def test(data):
        print data

    pool = ThreadPool()
    pool.run()
    for n in xrange(100):
        pool.add(n)
    pool.wait()

Example B:
    # thread pool chain
    # processes data which does not fit in queue (using iterator)
    # each result is forwarded to second pool which prints the result
    from thread_pool import ThreadPool
    from time import sleep

    def notify_result(message):
        print message

    def process_data(n):
        print n
        return (notify_result, ('Data %d' % n,), {})

    def source():
        for n in xrange(10000):
            yield (process_data, (n,), {})

    # iterates throught source iterator and fills input queue
    pool_a = ThreadPool(source=source())

    # create second pool
    pool_b = ThreadPool()
    # ... and set pool_b to process data from pool_a
    pool_a >> pool_b

    # start the pools
    pool_b.run()
    pool_a.run()
    # wait till all the workers return back from work
    pool_b.wait()
"""
import logging
from threading import Thread
from Queue import Queue, Empty, Full

from time import sleep
from datetime import datetime


class ThreadPool(object):

    def __init__(self, pool_size=30, source=None, queue_capacity=100, queue_timeout=0.5):
        """
        pool_size: maximum number of thread workers
        source: iterator, another ThreadPool or Queue or None to use method `add` to feed workers.
        queue_capacity: how many tasks can be queued using ThreadPool.add before Queue.Full exception is raised
        queue_timeout: how long each thread waits for a new job from empty queue before quits
        """
        self._pool_size = pool_size
        self._pool = []  # holds the list of created threads
        self._queue = Queue(queue_capacity)  # jobs in-queue
        self._queue_capacity = queue_capacity
        self._queue_timeout = queue_timeout
        self._source = None
        self._queue_out = None  # used to forward jobs results to another ThreadPool
        self.set_source(source)

    def add(self, callback, *args, **kwargs):
        """Adds a job to in-queue"""
        self._queue.put((callback, args, kwargs), timeout=self._queue_timeout)
        return self

    def wait(self):
        """Waits for all threads to finish"""
        self._queue.join()
        self.finish()
        return self

    def run(self):
        """
        Creates thread pool and starts to consume source (if any) or waits `queue_timeout` for jobs added by self.add
        """
        self.start()
        self._build_pool()
        if self._source is not None:
            consumer = Thread(target=self._consume)
            self._pool.append(consumer)
            consumer.start()
        return self

    def __rshift__(self, other):
        """
        Allows chaining of ThreadPool objects using pool_a >> pool_b
        other: consumer of self
        """
        return self.forward(other)

    def forward(self, other):
        """see __rshift__"""
        self._queue_out = Queue(self._queue_capacity)
        other.set_source(self._queue_out)
        return self

    def set_source(self, source):
        """
        Sets source (iterator, ThreadPool subclass or Queue instance)
        """
        if isinstance(source, Queue):
            self._queue = source
        elif isinstance(source, ThreadPool):
            source.forward(self)
        else:
            self._source = source

    def jobs_count(self):
        """Returns total count of jobs waiting and being processed"""
        return len(self._pool) + len(self._queue.qsize())

    def finish(self):
        """Called when self.wait finishes"""
        self._end_time = datetime.now()
        logging.debug('Finished in %s.' % (self._end_time - self._start_time))

    def start(self):
        """Called before any thread is created and started"""
        self._start_time = datetime.now()
        logging.debug('Starting.')

    def _build_pool(self):
        """Creates pool of running worker threads"""
        self._pool = []
        for n in xrange(self._pool_size):
            thread = Thread(target=self._thread_run)
            self._pool.append(thread)
            thread.start()
        return self

    def _consume(self):
        """Starts consumming source"""
        for job in self._source:
            if not len(job) == 3:
                raise ValueError("Job must bee tuple (callback, arg_list, kwargs_dict).")
            while True:
                try:
                    self.add(job[0], *job[1], **job[2])
                    break
                except Full:
                    sleep(0.1)
        return self

    def _clean_pool(self):
        """Removes finished threads from the pool."""
        self._pool = filter(lambda t: t.is_alive(), self._pool)
        return self

    def _thread_run(self):
        """
        Runs in thread and consumes the incomming jobs.
        """
        while True:
            try:
                job = self._queue.get(timeout=self._queue_timeout)
                try:
                    logging.debug('Running job.')
                    result = job[0](*job[1], **job[2])
                    if self._queue_out:
                        self._queue_out.put(result, timeout=self._queue_timeout)
                finally:
                    self._queue.task_done()
            except Empty:
                logging.debug('No jobs, quitting.')
                break
