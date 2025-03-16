# Files API Documentation

## List Files Endpoint

Retrieves a paginated list of files for the authenticated user with metadata from S3.

### Endpoint

```
GET /api/v2/files/
```

### Authentication

This endpoint requires authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | Integer | No | 1 | Page number for offset-based pagination |
| `per_page` | Integer | No | 50 | Number of items per page (max 100) |
| `cursor` | String | No | null | Cursor for cursor-based pagination (overrides page parameter) |
| `use_cache` | Boolean | No | true | Whether to use cached metadata or fetch fresh data from S3 |

### Pagination Options

The API supports two pagination methods:

1. **Offset-based pagination** (traditional): Use `page` and `per_page` parameters
2. **Cursor-based pagination** (more efficient): Use the `cursor` parameter

For large datasets, cursor-based pagination is recommended as it provides better performance.

### Response Format

```json
{
  "files": [
    {
      "file_name": "example.jpg",
      "simple_url": "https://bucket-url.com/username/example.jpg",
      "metadata": {
        "tier": "standard",
        "size": 1024000
      },
      "upload_complete": "complete",
      "last_modified": "2023-05-15T14:30:45.123Z",
      "id": "username/example.jpg",
      "s3_key": "username/example.jpg"
    },
    // ... more files
  ],
  "total": 120,
  "total_pages": 3,
  "page": 1,
  "per_page": 50,
  "next_cursor": "ts:2023-05-15T14:30:45.123Z"
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `files` | Array | List of file objects |
| `total` | Integer | Total number of files available |
| `total_pages` | Integer | Total number of pages (for offset-based pagination) |
| `page` | Integer | Current page number (for offset-based pagination) |
| `per_page` | Integer | Number of items per page |
| `next_cursor` | String | Cursor to use for the next page (for cursor-based pagination) |

#### File Object Fields

| Field | Type | Description |
|-------|------|-------------|
| `file_name` | String | Name of the file |
| `simple_url` | String | URL to access the file |
| `metadata` | Object | File metadata |
| `metadata.tier` | String | Storage tier (standard, glacier, etc.) |
| `metadata.size` | Integer | File size in bytes |
| `upload_complete` | String | Upload status (always "complete" for listed files) |
| `last_modified` | String | ISO 8601 timestamp of when the file was last modified |
| `id` | String | Unique identifier for the file |
| `s3_key` | String | S3 key for the file |

### Examples

#### Example 1: Basic Request (Offset-based Pagination)

Request:
```
GET /api/v2/files/?page=1&per_page=50
```

Response:
```json
{
  "files": [
    {
      "file_name": "document.pdf",
      "simple_url": "https://bucket-url.com/john-example/document.pdf",
      "metadata": {
        "tier": "standard",
        "size": 2048000
      },
      "upload_complete": "complete",
      "last_modified": "2023-06-10T09:15:30.456Z",
      "id": "john-example/document.pdf",
      "s3_key": "john-example/document.pdf"
    },
    // ... more files
  ],
  "total": 75,
  "total_pages": 2,
  "page": 1,
  "per_page": 50,
  "next_cursor": "ts:2023-06-10T09:15:30.456Z"
}
```

#### Example 2: Cursor-based Pagination

Initial request:
```
GET /api/v2/files/?per_page=20
```

Follow-up request (using the next_cursor from the previous response):
```
GET /api/v2/files/?cursor=ts:2023-06-10T09:15:30.456Z&per_page=20
```

#### Example 3: Bypassing Cache

Request:
```
GET /api/v2/files/?use_cache=false
```

This will fetch fresh metadata from S3 instead of using cached data.

### Error Responses

#### Invalid Pagination Parameters

```json
{
  "error": "Invalid pagination parameters. 'page' and 'per_page' must be positive integers."
}
```

#### Invalid Cursor Format

```json
{
  "error": "Invalid cursor format"
}
```

#### Server Error

```json
{
  "error": "Error message details"
}
```

### Implementation Notes for Frontend Developers

1. **Efficient Pagination**:
   - For small to medium datasets, traditional offset-based pagination works well
   - For large datasets, implement cursor-based pagination by storing and using the `next_cursor` value

2. **Handling Empty Results**:
   - If the `files` array is empty, display an appropriate message to the user
   - Check the `total` field to determine if there are no files at all or just no files on the current page

3. **Optimizing User Experience**:
   - Implement infinite scrolling or "Load More" buttons using the cursor-based pagination
   - Display loading indicators during API calls
   - Cache results client-side to improve perceived performance

4. **File Size Display**:
   - Convert the `metadata.size` from bytes to a human-readable format (KB, MB, GB)
   - Example: `const formattedSize = (size / (1024 * 1024)).toFixed(2) + ' MB'`

5. **Last Modified Date**:
   - Format the ISO 8601 timestamp in `last_modified` to a user-friendly date format
   - Example: `new Date(file.last_modified).toLocaleDateString()`

6. **Storage Tier Indication**:
   - Display different icons or labels based on the `metadata.tier` value
   - Example: Standard tier could have a regular icon, while Glacier tier could have a snowflake icon

### React Component Example

```jsx
import React, { useState, useEffect } from 'react';
import axios from 'axios';

const FilesList = () => {
  const [files, setFiles] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [nextCursor, setNextCursor] = useState(null);
  const [hasMore, setHasMore] = useState(true);

  const fetchFiles = async (cursor = null) => {
    setLoading(true);
    setError(null);
    
    try {
      const params = { per_page: 50 };
      if (cursor) {
        params.cursor = cursor;
      }
      
      const response = await axios.get('/api/v2/files/', {
        params,
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`
        }
      });
      
      if (cursor) {
        // Append to existing files for "load more" functionality
        setFiles(prevFiles => [...prevFiles, ...response.data.files]);
      } else {
        // Replace files for initial load or refresh
        setFiles(response.data.files);
      }
      
      setNextCursor(response.data.next_cursor);
      setHasMore(response.data.next_cursor !== null);
    } catch (err) {
      setError(err.response?.data?.error || 'An error occurred');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
  }, []);

  const loadMore = () => {
    if (nextCursor) {
      fetchFiles(nextCursor);
    }
  };

  const formatFileSize = (bytes) => {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + ' KB';
    if (bytes < 1024 * 1024 * 1024) return (bytes / (1024 * 1024)).toFixed(2) + ' MB';
    return (bytes / (1024 * 1024 * 1024)).toFixed(2) + ' GB';
  };

  const formatDate = (isoString) => {
    return new Date(isoString).toLocaleDateString();
  };

  return (
    <div className="files-list">
      <h2>Your Files</h2>
      
      {error && <div className="error-message">{error}</div>}
      
      {files.length === 0 && !loading ? (
        <p>No files found. Upload some files to get started.</p>
      ) : (
        <div className="files-grid">
          {files.map(file => (
            <div key={file.id} className="file-card">
              <div className="file-icon">
                {file.metadata.tier === 'glacier' ? '❄️' : '📄'}
              </div>
              <div className="file-details">
                <h3>{file.file_name}</h3>
                <p>Size: {formatFileSize(file.metadata.size)}</p>
                <p>Modified: {formatDate(file.last_modified)}</p>
                <p>Storage: {file.metadata.tier}</p>
              </div>
              <div className="file-actions">
                <a href={file.simple_url} target="_blank" rel="noopener noreferrer">
                  Download
                </a>
              </div>
            </div>
          ))}
        </div>
      )}
      
      {hasMore && (
        <button 
          onClick={loadMore} 
          disabled={loading}
          className="load-more-button"
        >
          {loading ? 'Loading...' : 'Load More'}
        </button>
      )}
    </div>
  );
};

export default FilesList;
```

## Get File Details Endpoint

Retrieves detailed information about a specific file, even if it only exists in S3 and not in the database.

### Endpoint

```
GET /api/files/{file_identifier}/details/
```

### Authentication

This endpoint requires authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_identifier` | String | Identifier for the file. Can be an s3_key, file_id, or filename |

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

### Response Format

```json
{
  "file_name": "example.jpg",
  "simple_url": "https://bucket-url.com/username/example.jpg",
  "metadata": {
    "tier": "standard",
    "size": 1024000,
    "content_type": "image/jpeg",
    "last_modified": "2023-05-15T14:30:45.123Z"
  },
  "upload_complete": "complete",
  "id": "username-example.jpg",
  "s3_key": "username/example.jpg",
  "exists_in_db": true
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `file_name` | String | Name of the file |
| `simple_url` | String | URL to access the file |
| `metadata` | Object | File metadata |
| `metadata.tier` | String | Storage tier (standard, glacier, etc.) |
| `metadata.size` | Integer | File size in bytes |
| `metadata.content_type` | String | MIME type of the file |
| `metadata.last_modified` | String | ISO 8601 timestamp of when the file was last modified |
| `upload_complete` | String | Upload status (always "complete" for files in S3) |
| `id` | String | Unique identifier for the file |
| `s3_key` | String | S3 key for the file |
| `exists_in_db` | Boolean | Whether the file exists in the MongoDB database |

### Error Responses

#### File Not Found

```json
{
  "error": "File not found in S3"
}
```

#### Server Error

```json
{
  "error": "Error message details"
}
```

### Example Usage

```javascript
// Example of fetching file details
const fetchFileDetails = async (fileIdentifier) => {
  try {
    const response = await axios.get(`/api/files/${fileIdentifier}/details/`, {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    
    return response.data;
  } catch (error) {
    console.error('Error fetching file details:', error);
    throw error;
  }
};

// Usage
const fileDetails = await fetchFileDetails('example.jpg');
console.log(`File size: ${formatFileSize(fileDetails.metadata.size)}`);
console.log(`Content type: ${fileDetails.metadata.content_type}`);
```

### Implementation Notes

1. This endpoint is useful for:
   - Getting detailed information about a specific file
   - Checking if a file exists in S3 before attempting to download it
   - Retrieving metadata for files that exist in S3 but not in the database

2. The `exists_in_db` field can be used to determine if the file is tracked in the database. Files that exist in S3 but not in the database might have been uploaded through other means.

3. For files stored in the Glacier tier, you'll need to restore them before downloading by using the appropriate restoration endpoints.

## Change File Storage Tier Endpoint

Changes the storage tier of a file between standard and glacier (archived) storage.

### Endpoint

```
POST /api/files/{file_identifier}/change_tier/
```

### Authentication

This endpoint requires authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Path Parameters

| Parameter | Type | Description |
|-----------|------|-------------|
| `file_identifier` | String | Identifier for the file. Can be an s3_key, file_id, MongoDB ObjectId, or filename |

The `file_identifier` can be:
- An s3_key (e.g., "username/filename.jpg")
- A file_id (e.g., "username-filename.jpg")
- A MongoDB ObjectId
- A filename (e.g., "filename.jpg") - in this case, the username prefix will be added automatically

### Request Body

```json
{
  "target_tier": "standard" or "glacier"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `target_tier` | String | Yes | The target storage tier. Must be either "standard" or "glacier" |

### Response Format (Success)

```json
{
  "message": "File successfully changed to glacier tier",
  "metadata": {
    "tier": "glacier",
    "content_type": "image/jpeg",
    "size": 1024000,
    "last_modified": "2023-05-15T14:30:45.123Z"
  }
}
```

### Response Format (Restoration Required)

```json
{
  "message": "File restoration initiated. Try changing the tier again after restoration is complete."
}
```

Status code: 202 Accepted

### Error Responses

#### File Not Found

```json
{
  "error": "File not found"
}
```

Status code: 404 Not Found

#### Invalid Request

```json
{
  "error": "target_tier is required and must be either \"standard\" or \"glacier\"."
}
```

Status code: 400 Bad Request

### Example Usage

```javascript
// Example of changing a file's storage tier
const changeFileTier = async (fileIdentifier, targetTier) => {
  try {
    const response = await axios.post(
      `/api/files/${fileIdentifier}/change_tier/`,
      { target_tier: targetTier },
      {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
          'Content-Type': 'application/json'
        }
      }
    );
    
    return response.data;
  } catch (error) {
    console.error('Error changing file tier:', error);
    throw error;
  }
};

// Usage
try {
  // Archive a file
  const result = await changeFileTier('example.jpg', 'glacier');
  console.log(`File archived: ${result.message}`);
  
  // Later, restore the file to standard tier
  const restoreResult = await changeFileTier('example.jpg', 'standard');
  if (restoreResult.status === 202) {
    console.log('File restoration initiated. Check back later.');
  } else {
    console.log(`File restored: ${restoreResult.message}`);
  }
} catch (error) {
  console.error('Failed to change file tier:', error.response?.data?.error || error.message);
}
```

### Implementation Notes

1. **Standard to Glacier**: This transition happens immediately and is completed in a single request.

2. **Glacier to Standard**: This is a two-step process:
   - First request initiates the restoration process (returns 202 Accepted)
   - After restoration is complete (which can take hours), a second request is needed to complete the transition

3. **Checking Restoration Status**: You can use the file details endpoint to check if a file is currently being restored:
   ```javascript
   const fileDetails = await fetchFileDetails('example.jpg');
   if (fileDetails.metadata.tier === 'unarchiving') {
     console.log('File is still being restored from Glacier');
   }
   ```

4. **Cost Considerations**: Be aware that:
   - Transitioning to Glacier is free
   - Restoring from Glacier incurs costs based on the amount of data and speed of restoration
   - Files in Glacier have a minimum 90-day storage duration for billing purposes

## Optimized List Files Endpoint (v3)

This is a high-performance version of the list files endpoint that significantly reduces response time, especially for large file collections.

### Endpoint

```
GET /api/v3/files/
```

### Authentication

This endpoint requires authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

### Request Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `page` | Integer | No | 1 | Page number for offset-based pagination |
| `per_page` | Integer | No | 50 | Number of items per page (max 1000) |
| `cursor` | String | No | null | Cursor for cursor-based pagination (overrides page parameter) |
| `use_cache` | Boolean | No | true | Whether to use cached results |

### Response Format

```json
{
  "files": [
    {
      "file_name": "example.jpg",
      "simple_url": "https://bucket-url.com/username/example.jpg",
      "metadata": {
        "tier": "standard",
        "size": 1024000,
        "content_type": "image/jpeg"
      },
      "upload_complete": "complete",
      "last_modified": "2023-05-15T14:30:45.123Z",
      "id": "username-example.jpg",
      "s3_key": "username/example.jpg",
      "exists_in_db": true
    },
    // ... more files
  ],
  "total": 120,
  "total_pages": 3,
  "page": 1,
  "per_page": 50,
  "next_cursor": "eyJrZXkiOiJ1c2VybmFtZS9leGFtcGxlLmpwZyJ9"
}
```

### Performance Improvements

This endpoint offers several performance advantages over the v2 endpoint:

1. **Reduced API Calls**: Uses S3's `list_objects_v2` API to get multiple files in a single call instead of making individual `head_object` calls for each file
2. **Response Caching**: Caches entire responses for 5 minutes to avoid redundant S3 API calls
3. **Efficient Pagination**: Uses S3's native pagination mechanisms for better performance
4. **Automatic Cache Expiration**: Cache entries automatically expire after 1 hour

### Example Usage

```javascript
// Example of fetching files with the optimized endpoint
const fetchFilesOptimized = async (cursor = null) => {
  try {
    const params = { per_page: 50 };
    if (cursor) {
      params.cursor = cursor;
    }
    
    const response = await axios.get('/api/v3/files/', {
      params,
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    
    return response.data;
  } catch (error) {
    console.error('Error fetching files:', error);
    throw error;
  }
};

// Usage
const { files, next_cursor } = await fetchFilesOptimized();
console.log(`Fetched ${files.length} files`);

// Fetch next page if available
if (next_cursor) {
  const nextPage = await fetchFilesOptimized(next_cursor);
  console.log(`Fetched ${nextPage.files.length} more files`);
}
```

### Limitations

1. **Content Type**: The `content_type` field may not be available for files that only exist in S3 and not in the database, as this information is not returned by the `list_objects_v2` API
2. **Cache Freshness**: If files are added or removed directly in S3, the cached results may be stale for up to 5 minutes
3. **Maximum Items**: The `per_page` parameter is limited to 1000 items to prevent excessive memory usage

## Flexible File Identification

All file-specific endpoints now support multiple ways to identify a file:

### Supported File Identifiers

The following endpoints now accept multiple types of file identifiers:
- `GET /api/files/{file_identifier}/details/`
- `GET /api/files/{file_identifier}/download_file/`
- `GET /api/files/{file_identifier}/download_presigned_url/`
- `GET /api/files/{file_identifier}/refresh`

Each of these endpoints can identify files using:
- **S3 Key**: The full S3 key path (e.g., "username/filename.jpg")
- **File ID**: The ID stored in the database (e.g., "username-filename.jpg")
- **MongoDB ObjectId**: The MongoDB document ID
- **Filename**: Just the filename (e.g., "filename.jpg") - the username prefix will be added automatically

### Benefits

This flexible identification system provides several benefits:
1. **Improved Robustness**: Files can be accessed even if they're stored differently than expected
2. **S3-First Approach**: Files that exist in S3 but not in the database can still be accessed
3. **User-Friendly URLs**: Users can use simple filenames in URLs instead of complex identifiers
4. **Backward Compatibility**: All existing file references continue to work

### Example Usage

```javascript
// All of these will work for the same file:
await fetchFileDetails('example.jpg');
await fetchFileDetails('username-example.jpg');
await fetchFileDetails('username/example.jpg');
await fetchFileDetails('507f1f77bcf86cd799439011'); // MongoDB ObjectId
``` 