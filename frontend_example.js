// React component example for multi-file upload
import React, { useState } from 'react';
import axios from 'axios';

const MultiFileUpload = () => {
  const [files, setFiles] = useState([]);
  const [uploading, setUploading] = useState(false);
  const [uploadProgress, setUploadProgress] = useState({});
  const [uploadResults, setUploadResults] = useState([]);

  // Handle file selection
  const handleFileChange = (e) => {
    setFiles([...e.target.files]);
  };

  // Handle upload
  const handleUpload = async () => {
    if (files.length === 0) {
      alert('Please select at least one file to upload');
      return;
    }

    setUploading(true);
    setUploadProgress({});
    setUploadResults([]);

    try {
      // Step 1: Prepare file metadata for the API
      const filesData = files.map(file => ({
        file_name: file.name,
        content_type: file.type,
        file_size: file.size,
        tier: 'standard' // You can make this configurable
      }));

      // Step 2: Get presigned URLs from the backend
      const response = await axios.post('/api/files/upload/', {
        files: filesData
      }, {
        headers: {
          'Authorization': `Bearer ${localStorage.getItem('token')}`,
          'Content-Type': 'application/json'
        }
      });

      // Step 3: Upload files to S3 using the presigned URLs
      const successfulUploads = response.data.successful;
      const s3Keys = [];
      
      // Create an array of upload promises
      const uploadPromises = successfulUploads.map(async (fileData, index) => {
        const file = files.find(f => f.name === fileData.file_name);
        if (!file) return null;

        // Initialize progress for this file
        setUploadProgress(prev => ({
          ...prev,
          [fileData.file_name]: 0
        }));

        try {
          // Upload to S3 with progress tracking
          await axios.put(fileData.presigned_url, file, {
            headers: {
              'Content-Type': file.type
            },
            onUploadProgress: (progressEvent) => {
              const percentCompleted = Math.round(
                (progressEvent.loaded * 100) / progressEvent.total
              );
              
              setUploadProgress(prev => ({
                ...prev,
                [fileData.file_name]: percentCompleted
              }));
            }
          });

          // Add to successful uploads
          s3Keys.push(fileData.s3_key);
          return {
            file_name: fileData.file_name,
            status: 'success',
            s3_key: fileData.s3_key
          };
        } catch (error) {
          console.error(`Error uploading ${fileData.file_name}:`, error);
          return {
            file_name: fileData.file_name,
            status: 'error',
            error: error.message
          };
        }
      });

      // Wait for all uploads to complete
      const results = await Promise.all(uploadPromises);
      setUploadResults(results.filter(r => r !== null));

      // Step 4: Confirm uploads with the backend
      if (s3Keys.length > 0) {
        await axios.post('/api/files/confirm_uploads/', {
          s3_keys: s3Keys
        }, {
          headers: {
            'Authorization': `Bearer ${localStorage.getItem('token')}`,
            'Content-Type': 'application/json'
          }
        });
      }

      alert(`Successfully uploaded ${s3Keys.length} files`);
    } catch (error) {
      console.error('Upload error:', error);
      alert(`Error: ${error.response?.data?.error || error.message}`);
    } finally {
      setUploading(false);
    }
  };

  return (
    <div className="upload-container">
      <h2>Multi-File Upload</h2>
      
      <div className="file-input">
        <input
          type="file"
          multiple
          onChange={handleFileChange}
          disabled={uploading}
        />
        <button 
          onClick={handleUpload} 
          disabled={uploading || files.length === 0}
        >
          {uploading ? 'Uploading...' : 'Upload Files'}
        </button>
      </div>
      
      {files.length > 0 && (
        <div className="selected-files">
          <h3>Selected Files:</h3>
          <ul>
            {files.map((file, index) => (
              <li key={index}>
                {file.name} ({(file.size / 1024 / 1024).toFixed(2)} MB)
                {uploading && uploadProgress[file.name] !== undefined && (
                  <div className="progress-bar">
                    <div 
                      className="progress" 
                      style={{ width: `${uploadProgress[file.name]}%` }}
                    />
                    <span>{uploadProgress[file.name]}%</span>
                  </div>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
      
      {uploadResults.length > 0 && (
        <div className="upload-results">
          <h3>Upload Results:</h3>
          <ul>
            {uploadResults.map((result, index) => (
              <li key={index} className={`result-${result.status}`}>
                {result.file_name}: {result.status === 'success' 
                  ? 'Uploaded successfully' 
                  : `Failed - ${result.error}`}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
};

export default MultiFileUpload; 