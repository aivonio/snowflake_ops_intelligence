import time

class MockResult:
    def __init__(self, data):
        self.data = data
    def collect(self):
        # Simulate network latency
        time.sleep(0.05)
        return self.data

class MockSession:
    def __init__(self, num_users=10, queries_per_user=5):
        self.num_users = num_users
        self.queries_per_user = queries_per_user

    def sql(self, query):
        if "QUERY_ID" in query and "GROUP BY" not in query:
            # Original query returning individual queries
            data = [{'QUERY_ID': f"Q_{u}_{q}"} for u in range(self.num_users) for q in range(self.queries_per_user)]
            return MockResult(data)
        elif "Q_COUNT" in query:
            # Optimized query returning users and counts
            data = [{'USER_NAME': f"U_{u}", 'Q_COUNT': self.queries_per_user} for u in range(self.num_users)]
            return MockResult(data)
        elif "SYSTEM$CANCEL_QUERY" in query:
            return MockResult([])
        elif "SYSTEM$CANCEL_ALL_QUERIES" in query:
            return MockResult([])
        return MockResult([])

def original_method(session, safe_target):
    start = time.time()
    running = session.sql(
        f"SELECT qh.QUERY_ID "
        f"FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER()) qh "
        f"JOIN APP_CONTEXT.TEAM_ATTRIBUTION ta ON qh.USER_NAME = ta.USER_NAME "
        f"WHERE ta.TEAM_NAME = '{safe_target}' "
        f"AND qh.EXECUTION_STATUS = 'RUNNING'"
    ).collect()
    cancelled = 0
    for qrow in running:
        try:
            session.sql(f"SELECT SYSTEM$CANCEL_QUERY('{qrow['QUERY_ID']}')").collect()
            cancelled += 1
        except:
            pass
    return time.time() - start

def optimized_method(session, safe_target):
    start = time.time()
    running_users = session.sql(
        f"SELECT qh.USER_NAME, COUNT(*) as Q_COUNT "
        f"FROM TABLE(INFORMATION_SCHEMA.QUERY_HISTORY_BY_USER()) qh "
        f"JOIN APP_CONTEXT.TEAM_ATTRIBUTION ta ON qh.USER_NAME = ta.USER_NAME "
        f"WHERE ta.TEAM_NAME = '{safe_target}' "
        f"AND qh.EXECUTION_STATUS = 'RUNNING' "
        f"GROUP BY qh.USER_NAME"
    ).collect()

    cancelled_queries = 0
    for urow in running_users:
        try:
            session.sql(f"SELECT SYSTEM$CANCEL_ALL_QUERIES('{urow['USER_NAME']}')").collect()
            cancelled_queries += urow['Q_COUNT']
        except:
            pass
    return time.time() - start

if __name__ == "__main__":
    session = MockSession(num_users=5, queries_per_user=10)

    t1 = original_method(session, "team_a")
    print(f"Original Method: {t1:.4f}s")

    t2 = optimized_method(session, "team_a")
    print(f"Optimized Method: {t2:.4f}s")

    if t1 > 0:
        improvement = (t1 - t2) / t1 * 100
        print(f"Improvement: {improvement:.2f}%")
