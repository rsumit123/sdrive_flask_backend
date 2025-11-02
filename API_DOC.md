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

This endpoint lists files using standard page-based pagination. It queries the database for the file list and then fetches metadata from S3 for each file on the current page.

*Note: While simpler, this approach might be slower than cursor-based pagination for very large datasets due to multiple S3 API calls per page.*

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
| `page` | Integer | No | 1 | Page number to retrieve (starts at 1) |
| `per_page` | Integer | No | 50 | Number of items per page (max 100 recommended) |


### Response Format

```json
{
  "files": [
    {
      "file_name": "report_final.pdf",
      "simple_url": "https://bucket-url.com/username/report_final.pdf",
      "metadata": {
        "tier": "standard",
        "size": 512000,
        "content_type": "application/pdf"
      },
      "upload_complete": "complete",
      "last_modified": "2023-06-15T11:05:00.000Z",
      "id": "username-report_final.pdf",
      "s3_key": "username/report_final.pdf",
      "exists_in_db": true
    },
    {
      "file_name": "image_backup.zip",
      "simple_url": "https://bucket-url.com/username/image_backup.zip",
      "metadata": {
        "tier": "standard",
        "size": 157286400,
        "content_type": "application/zip"
      },
      "upload_complete": "complete",
      "last_modified": "2023-06-14T16:45:10.000Z",
      "id": "username-image_backup.zip",
      "s3_key": "username/image_backup.zip",
      "exists_in_db": true
    }
    // ... more files (up to per_page)
  ],
  "total": 78,
  "total_pages": 2,
  "page": 1,
  "per_page": 50
}
```

#### Response Fields Explanation

-   `files`: An array containing the file objects for the current page, sorted by `last_modified` date (descending, based on database sort).
-   `total`: The total number of files available for the user.
-   `total_pages`: The total number of pages available based on `per_page`.
-   `page`: The current page number being returned.
-   `per_page`: The number of items requested per page.

### Implementation Details

1.  **Database Query**: The endpoint first queries the database to find the files belonging to the user, applying the `page` and `per_page` parameters using `skip` and `limit`.
2.  **Sorting**: Files are sorted primarily by `last_modified` date (descending) in the database query.
3.  **S3 Metadata Fetch**: For each file record retrieved from the database for the current page, a separate `head_object` call is made to S3 (in parallel) to get the latest metadata (like size and storage tier).
4.  **No Caching/Cursors**: This version does not use application-level caching or S3 continuation tokens (cursors).

### Important Considerations

-   **Performance**: Fetching S3 metadata for each file individually can be slow if `per_page` is high or if there's high latency to S3. Consider keeping `per_page` at a reasonable value (e.g., 50 or lower).
-   **S3 Eventual Consistency**: While the list of files comes from the database (which should be consistent after `confirm_upload`), the metadata (size, tier) fetched from S3 might reflect eventual consistency if the file was *very* recently modified directly in S3 outside the app's flow.
-   **DB vs S3 Discrepancies**: If a file record exists in the database but the corresponding object is missing from S3 (e.g., deleted externally), it will be logged on the server and omitted from the `files` array in the response.

### Example Usage (Frontend - Page-based)

```javascript
const [files, setFiles] = useState([]);
const [currentPage, setCurrentPage] = useState(1);
const [totalPages, setTotalPages] = useState(0);
const [loading, setLoading] = useState(false);

const fetchFilesPageBased = async (page = 1) => {
  if (loading) return;
  setLoading(true);
  try {
    const params = { page: page, per_page: 50 };
    
    const response = await axios.get('/api/v3/files/', {
      params,
      headers: { 'Authorization': `Bearer ${localStorage.getItem('token')}` }
    });
    
    setFiles(response.data.files);
    setCurrentPage(response.data.page);
    setTotalPages(response.data.total_pages);

  } catch (error) {
    console.error('Error fetching files:', error);
    // Handle error appropriately in UI
  } finally {
    setLoading(false);
  }
};

// Initial load
useEffect(() => {
  fetchFilesPageBased(1);
}, []);

// Example: Go to next page
const handleNextPage = () => {
  if (currentPage < totalPages) {
    fetchFilesPageBased(currentPage + 1);
  }
};

// Example: Go to previous page
const handlePrevPage = () => {
  if (currentPage > 1) {
    fetchFilesPageBased(currentPage - 1);
  }
};
```

### Limitations

1.  **Performance**: As noted, can be slower than cursor-based methods for large pages/datasets.
2.  **Maximum `per_page`**: While the code allows up to 100, a lower value (<= 50) is recommended for better performance due to the S3 `head_object` calls.

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

## Check Account Usage Endpoint

Retrieves account usage statistics for the authenticated user, including total file count, total storage size, and breakdown by storage tier.

### Endpoint

```
GET /api/account/check_account_usage/
```

### Authentication

This endpoint requires authentication. Include the JWT token in the Authorization header:

```
Authorization: Bearer <your_jwt_token>
```

Or using the `x-access-token` header:

```
x-access-token: <your_jwt_token>
```

### Request Parameters

This endpoint does not require any query parameters.

### Response Format

```json
{
  "total_files": 150,
  "total_file_size": 5242880000,
  "total_file_size_mb": 5000.0,
  "total_file_size_gb": 4.88,
  "files_in_standard": 120,
  "files_in_archive": 30
}
```

#### Response Fields

| Field | Type | Description |
|-------|------|-------------|
| `total_files` | Integer | Total number of files uploaded by the user |
| `total_file_size` | Integer | Total size of all uploaded files in bytes |
| `total_file_size_mb` | Float | Total file size in megabytes (MB), rounded to 2 decimal places |
| `total_file_size_gb` | Float | Total file size in gigabytes (GB), rounded to 2 decimal places |
| `files_in_standard` | Integer | Number of files stored in standard storage tier |
| `files_in_archive` | Integer | Number of files stored in archive/glacier storage tier |

### Storage Tier Classification

- **Standard**: Files stored with `STANDARD` storage class in S3
- **Archive**: Files stored with `GLACIER` or `DEEP_ARCHIVE` storage class in S3

### Examples

#### Example 1: Basic Request

Request:
```javascript
const response = await fetch('/api/account/check_account_usage/', {
  method: 'GET',
  headers: {
    'Authorization': `Bearer ${token}`,
    'Content-Type': 'application/json'
  }
});

const usage = await response.json();
console.log(`Total files: ${usage.total_files}`);
console.log(`Total storage: ${usage.total_file_size_gb} GB`);
console.log(`Standard files: ${usage.files_in_standard}`);
console.log(`Archive files: ${usage.files_in_archive}`);
```

Response:
```json
{
  "total_files": 150,
  "total_file_size": 5242880000,
  "total_file_size_mb": 5000.0,
  "total_file_size_gb": 4.88,
  "files_in_standard": 120,
  "files_in_archive": 30
}
```

#### Example 2: Using Axios

```javascript
import axios from 'axios';

const getAccountUsage = async () => {
  try {
    const response = await axios.get('/api/account/check_account_usage/', {
      headers: {
        'Authorization': `Bearer ${localStorage.getItem('token')}`
      }
    });
    
    const usage = response.data;
    
    // Display usage in UI
    document.getElementById('total-files').textContent = usage.total_files;
    document.getElementById('total-size').textContent = `${usage.total_file_size_gb} GB`;
    document.getElementById('standard-files').textContent = usage.files_in_standard;
    document.getElementById('archive-files').textContent = usage.files_in_archive;
    
    return usage;
  } catch (error) {
    console.error('Error fetching account usage:', error);
    throw error;
  }
};

// Call the function
getAccountUsage();
```

#### Example 3: React Hook

```javascript
import { useState, useEffect } from 'react';
import axios from 'axios';

const useAccountUsage = () => {
  const [usage, setUsage] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    const fetchUsage = async () => {
      try {
        setLoading(true);
        const response = await axios.get('/api/account/check_account_usage/', {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`
          }
        });
        setUsage(response.data);
      } catch (err) {
        setError(err.message);
      } finally {
        setLoading(false);
      }
    };

    fetchUsage();
  }, []);

  return { usage, loading, error };
};

// Usage in component
const AccountUsageDisplay = () => {
  const { usage, loading, error } = useAccountUsage();

  if (loading) return <div>Loading usage statistics...</div>;
  if (error) return <div>Error: {error}</div>;
  if (!usage) return null;

  return (
    <div className="usage-stats">
      <h2>Account Usage</h2>
      <div>
        <p>Total Files: {usage.total_files}</p>
        <p>Total Storage: {usage.total_file_size_gb} GB ({usage.total_file_size_mb} MB)</p>
        <p>Standard Tier: {usage.files_in_standard} files</p>
        <p>Archive Tier: {usage.files_in_archive} files</p>
      </div>
    </div>
  );
};
```

### Implementation Details

1. **Data Sources**: The endpoint aggregates data from MongoDB and S3:
   - First checks MongoDB for cached file metadata (size and tier)
   - Falls back to fetching from S3 if metadata is missing
   - Uses parallel S3 API calls for efficiency when fetching missing data

2. **Performance Considerations**:
   - For users with many files, the endpoint may make multiple S3 API calls
   - The endpoint uses parallel processing to minimize latency
   - Consider caching the response on the frontend to reduce API calls

3. **Accuracy**:
   - File counts are based on MongoDB records with `upload_complete: "complete"`
   - File sizes are retrieved from S3 or cached metadata
   - Tier classification is based on S3 storage class

### Error Responses

#### 401 Unauthorized
```json
{
  "error": "Token is missing!"
}
```

#### 403 Forbidden
```json
{
  "error": "Invalid token!"
}
```

#### 500 Internal Server Error
```json
{
  "error": "Failed to retrieve account usage statistics"
}
```

### Best Practices

1. **Caching**: Cache the response on the frontend and refresh periodically (e.g., every 5-10 minutes)
2. **Error Handling**: Always handle errors gracefully and provide user feedback
3. **Loading States**: Show loading indicators while fetching usage statistics
4. **Refresh**: Provide a manual refresh button for users to update their usage stats on demand

### Integration Notes

- This endpoint is designed to be called periodically to display account usage in the UI
- The response includes both raw bytes and human-readable MB/GB values for convenience
- The tier breakdown helps users understand their storage distribution between standard and archive storage 