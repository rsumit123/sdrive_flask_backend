# List Files API Optimization

This document outlines the optimizations made to the `list_files_v2` function to improve performance and efficiency.

## Optimizations Implemented

### 1. Parallel S3 API Calls

**Problem:** The original implementation made sequential S3 `head_object` calls for each file, which was inefficient for large numbers of files.

**Solution:** Implemented parallel processing using `ThreadPoolExecutor` to make multiple S3 API calls concurrently, significantly reducing the time needed to fetch metadata for multiple files.

```python
with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
    s3_results = list(executor.map(get_s3_metadata, file_records))
```

### 2. Cursor-Based Pagination

**Problem:** Offset-based pagination using `skip()` becomes inefficient for large collections as MongoDB must scan and discard all documents before the skip point.

**Solution:** Added support for cursor-based pagination as an alternative, which uses a cursor (based on the last item's timestamp) to efficiently fetch the next page of results.

```python
if cursor.startswith('ts:'):
    # Timestamp-based cursor
    timestamp = cursor[3:]
    query = {
        "upload_complete": "complete", 
        "s3_key": {"$regex": f"^{prefix}/"},
        "last_modified": {"$lt": timestamp}
    }
```

### 3. Metadata Caching

**Problem:** Each request required fresh S3 API calls, even if the metadata hadn't changed.

**Solution:** Implemented a caching mechanism that stores S3 metadata in MongoDB, reducing the need for frequent S3 API calls. The cache has a configurable TTL (default: 1 hour).

```python
# Check if we have cached metadata that's not expired
if use_cache and 'cached_metadata' in record and 'metadata_cached_at' in record:
    cache_time = record['metadata_cached_at']
    if datetime.datetime.utcnow() - cache_time < cache_ttl:
        # Use cached metadata
        return record['cached_metadata']
```

### 4. MongoDB Indexing

**Problem:** Queries on the `files` collection could be slow without proper indexes.

**Solution:** Added appropriate indexes to optimize the most common query patterns:

```python
# Index for s3_key prefix queries and upload_complete status
db.files.create_index([("s3_key", 1), ("upload_complete", 1)])

# Index for sorting by last_modified
db.files.create_index([("last_modified", -1)])

# Compound index for the most common query pattern
db.files.create_index([
    ("upload_complete", 1),
    ("s3_key", 1),
    ("last_modified", -1)
])
```

## Performance Improvements

These optimizations provide several benefits:

1. **Reduced Response Time:** Parallel S3 API calls significantly reduce the time needed to fetch metadata for multiple files.
2. **Improved Scalability:** Cursor-based pagination allows efficient navigation through large datasets without performance degradation.
3. **Reduced S3 API Usage:** Metadata caching reduces the number of S3 API calls, which can save costs and improve performance.
4. **Faster Database Queries:** Proper indexing ensures that MongoDB queries are efficient, even with large collections.

## Usage

### Offset-Based Pagination (Original)

```
GET /api/v2/files/?page=1&per_page=50
```

### Cursor-Based Pagination (New)

Initial request:
```
GET /api/v2/files/?per_page=50
```

Subsequent requests (using the next_cursor from the previous response):
```
GET /api/v2/files/?cursor=ts:2023-05-15T14:30:45.123Z&per_page=50
```

### Cache Control

To bypass the cache and force fresh S3 metadata:
```
GET /api/v2/files/?use_cache=false
```

## Limitations and Considerations

1. **Cache Staleness:** Cached metadata might become stale if files are modified directly in S3. The cache TTL (1 hour by default) helps mitigate this issue.
2. **S3 Rate Limits:** While parallel processing improves performance, be mindful of S3 API rate limits. The `max_workers` parameter (10 by default) controls the maximum number of concurrent S3 API calls.
3. **Memory Usage:** Processing large numbers of files in parallel can increase memory usage. Adjust the `per_page` parameter accordingly. 