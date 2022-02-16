import django_redis

from . import utils

class ConnectionFactory(django_redis.pool.ConnectionFactory):
    def get_or_create_connection_pool(self, params):
        """
        Given a connection parameters and return a new
        or cached connection pool for them.
        """
        key = (params["url"],utils.to_mapkey(self.pool_cls_kwargs))
        if key not in self._pools:
            self._pools[key] = self.get_connection_pool(params)
        return self._pools[key]

