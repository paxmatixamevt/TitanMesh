let currentTab = 'send';
let sessionKeys = null;

function switchTab(tab) {
    currentTab = tab;
    
    // Update tab buttons
    document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
    event.target.classList.add('active');
    
    // Show/hide tab content
    document.querySelectorAll('.tab-content').forEach(c => c.style.display = 'none');
    document.getElementById(`tab-${tab}`).style.display = 'block';
    
    // Refresh content
    if (tab === 'inbox') refreshInbox();
    if (tab === 'sent') refreshSentMessages();
}

async function loadAllData() {
    await Promise.all([
        checkSession(),
        loadStatus(),
        loadPeers(),
        refreshInbox(),
        refreshSentMessages()
    ]);
}

async function apiCall(url, options = {}) {
    try {
        const response = await fetch(url, options);
        if (!response.ok) {
            const errorData = await response.json().catch(() => ({}));
            throw new Error(errorData.error || `HTTP ${response.status}`);
        }
        return await response.json();
    } catch (error) {
        console.error(`API call failed: ${url}`, error);
        throw error;
    }
}

// ============================================================
// KEY MANAGEMENT FUNCTIONS
// ============================================================

async function generateKeys() {
    const btn = document.getElementById('generateKeysBtn');
    btn.disabled = true;
    btn.textContent = 'Generating...';
    
    try {
        const data = await apiCall('/api/keys/generate', {
            method: 'POST'
        });
        
        if (data.success) {
            // Display keys
            document.getElementById('publicKey').textContent = data.public_key;
            document.getElementById('publicKey').classList.remove('loading');
            document.getElementById('privateKey').textContent = data.private_key;
            document.getElementById('privateKey').classList.remove('loading');
            
            // Show success message
            showKeyStatus('Keys generated successfully! Click "Set Session Keys" to use them.', 'success');
            
            // Enable set session button
            document.getElementById('setSessionBtn').disabled = false;
            
            // Store keys temporarily for session
            sessionKeys = {
                private_key: data.private_key,
                public_key: data.public_key
            };
        } else {
            showKeyStatus('Failed to generate keys: ' + data.error, 'error');
        }
    } catch (error) {
        showKeyStatus('Failed to generate keys: ' + error.message, 'error');
    }
    
    btn.disabled = false;
    btn.textContent = 'Generate New Keys';
}

async function setSessionKeys() {
    const privateKey = document.getElementById('privateKey').textContent;
    
    if (!privateKey || privateKey === 'No keys generated' || privateKey === 'Failed to load') {
        showKeyStatus('Please generate or import keys first!', 'error');
        return;
    }
    
    try {
        const data = await apiCall('/api/session/set_keys', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({private_key: privateKey})
        });
        
        if (data.success) {
            showKeyStatus('✅ Keys set for this session! You can now send and receive messages.', 'success');
            document.getElementById('sessionStatus').textContent = '✅ Active';
            document.getElementById('sessionStatus').style.color = '#4ade80';
            
            // Enable send button
            document.getElementById('sendBtn').disabled = false;
            
            // Reload data
            await loadAllData();
        } else {
            showKeyStatus('Failed to set session: ' + data.error, 'error');
        }
    } catch (error) {
        showKeyStatus('Failed to set session: ' + error.message, 'error');
    }
}

async function clearSession() {
    try {
        await apiCall('/api/session/clear_keys', {
            method: 'POST'
        });
        
        showKeyStatus('Session keys cleared.', 'info');
        document.getElementById('sessionStatus').textContent = '❌ Not Set';
        document.getElementById('sessionStatus').style.color = '#f87171';
        document.getElementById('sendBtn').disabled = true;
        
        // Clear keys display
        document.getElementById('publicKey').textContent = 'No keys loaded';
        document.getElementById('privateKey').textContent = 'No keys loaded';
        document.getElementById('setSessionBtn').disabled = true;
        
    } catch (error) {
        showKeyStatus('Failed to clear session: ' + error.message, 'error');
    }
}

async function checkSession() {
    try {
        const data = await apiCall('/api/session/status');
        
        if (data.has_keys) {
            document.getElementById('sessionStatus').textContent = '✅ Active';
            document.getElementById('sessionStatus').style.color = '#4ade80';
            document.getElementById('sendBtn').disabled = false;
            
            // Show public key
            document.getElementById('publicKey').textContent = data.public_key || 'Loaded';
            document.getElementById('publicKey').classList.remove('loading');
            
            // Private key is not returned for security
            document.getElementById('privateKey').textContent = '🔒 (hidden for security)';
            document.getElementById('privateKey').classList.remove('loading');
            document.getElementById('privateKey').style.fontFamily = 'inherit';
            
            document.getElementById('setSessionBtn').disabled = true;
        } else {
            document.getElementById('sessionStatus').textContent = '❌ Not Set';
            document.getElementById('sessionStatus').style.color = '#f87171';
            document.getElementById('sendBtn').disabled = true;
            
            if (!document.getElementById('publicKey').textContent.includes('generated')) {
                document.getElementById('publicKey').textContent = 'No keys loaded';
                document.getElementById('privateKey').textContent = 'No keys loaded';
            }
        }
    } catch (error) {
        console.error('Failed to check session:', error);
    }
}

function showKeyStatus(message, type) {
    const statusDiv = document.getElementById('keyStatus');
    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type} show`;
    setTimeout(() => statusDiv.classList.remove('show'), 10000);
}

async function exportKeys() {
    const privateKey = document.getElementById('privateKey').textContent;
    
    if (!privateKey || privateKey === 'No keys generated' || privateKey === 'Failed to load' || privateKey.includes('hidden')) {
        showKeyStatus('No keys to export. Generate or import keys first.', 'error');
        return;
    }
    
    try {
        // We need to get the keys from session or generate
        const data = {
            private_key: privateKey,
            public_key: document.getElementById('publicKey').textContent,
            exported_at: Math.floor(Date.now() / 1000)
        };
        
        const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'titanmesh_keys.json';
        a.click();
        window.URL.revokeObjectURL(url);
        showKeyStatus('Keys exported successfully!', 'success');
    } catch (error) {
        showKeyStatus('Failed to export keys: ' + error.message, 'error');
    }
}

async function importKeys(file) {
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        const privateKey = data.private_key;
        if (!privateKey) {
            showKeyStatus('Invalid key file - no private key found', 'error');
            return;
        }
        
        // Validate the key
        const validateData = await apiCall('/api/keys/validate', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({private_key: privateKey})
        });
        
        if (!validateData.valid) {
            showKeyStatus('Invalid private key format', 'error');
            return;
        }
        
        // Display the keys
        document.getElementById('publicKey').textContent = validateData.public_key;
        document.getElementById('publicKey').classList.remove('loading');
        document.getElementById('privateKey').textContent = privateKey;
        document.getElementById('privateKey').classList.remove('loading');
        
        showKeyStatus('Keys imported successfully! Click "Set Session Keys" to use them.', 'success');
        document.getElementById('setSessionBtn').disabled = false;
        
        // Store for session
        sessionKeys = {
            private_key: privateKey,
            public_key: validateData.public_key
        };
        
    } catch (error) {
        showKeyStatus('Failed to import keys: ' + error.message, 'error');
    }
}

// ============================================================
// DATA MANAGEMENT FUNCTIONS
// ============================================================

async function exportData() {
    try {
        const response = await fetch('/api/data/export');
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'titanmesh_data.json';
        a.click();
        window.URL.revokeObjectURL(url);
    } catch (error) {
        alert('Failed to export data: ' + error.message);
    }
}

async function importData(file) {
    try {
        const text = await file.text();
        const data = JSON.parse(text);
        
        const response = await apiCall('/api/data/import', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(data)
        });
        
        if (response.success) {
            alert('Data imported successfully!');
            await loadAllData();
        } else {
            alert('Failed to import data: ' + response.error);
        }
    } catch (error) {
        alert('Failed to import data: ' + error.message);
    }
}

// ============================================================
// REMOTE SYNC
// ============================================================

async function remoteSync() {
    const peerUrl = document.getElementById('peerSyncUrl').value.trim();
    const statusDiv = document.getElementById('syncStatus');
    
    if (!peerUrl) {
        alert('Please enter a peer URL (e.g., http://localhost:5001)');
        return;
    }
    
    statusDiv.textContent = 'Syncing...';
    
    try {
        const response = await apiCall('/api/sync/remote', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({peer_url: peerUrl})
        });
        
        if (response.success) {
            statusDiv.textContent = response.message + ` (Height: ${response.our_height})`;
            await loadAllData();
        } else {
            statusDiv.textContent = 'Sync failed: ' + response.error;
        }
    } catch (error) {
        statusDiv.textContent = 'Sync failed: ' + error.message;
    }
}

// ============================================================
// STATUS AND PEERS
// ============================================================

async function loadStatus() {
    try {
        const status = await apiCall('/api/status');
        document.getElementById('peerCount').textContent = `${status.peers || 0} peers`;
        document.getElementById('blockCount').textContent = status.total_blocks || 0;
        document.getElementById('inboxCount').textContent = `${status.inbox_count || 0} (${status.unread_count || 0} unread)`;
        document.getElementById('statBlocks').textContent = status.total_blocks || 0;
        document.getElementById('statMessages').textContent = status.total_messages || 0;
        document.getElementById('statPending').textContent = status.pending_messages || 0;
        document.getElementById('statSent').textContent = status.sent_count || 0;
        document.getElementById('statPeers').textContent = status.known_peers || 0;
    } catch (error) {
        document.getElementById('peerCount').textContent = 'Error';
    }
}

async function loadPeers() {
    try {
        const data = await apiCall('/api/peers');
        const peersList = document.getElementById('peersList');
        
        let html = '';
        
        if (data.stored_peers && data.stored_peers.length > 0) {
            data.stored_peers.forEach(peer => {
                html += `<div class="peer-item">
                    <span>${peer.node_id}</span>
                    <span style="color: #94a3b8; font-size: 11px;">${peer.address}:${peer.api_port}</span>
                </div>`;
            });
        }
        
        if (data.connected_peers && data.connected_peers.length > 0) {
            data.connected_peers.forEach(peer => {
                html += `<div class="peer-item">
                    <span>WS: ${peer.peer_id}...</span>
                    <span style="color: #4ade80;">connected</span>
                </div>`;
            });
        }
        
        if (!html) {
            html = '<div class="peer-item" style="color: #94a3b8;">No peers found</div>';
        }
        
        peersList.innerHTML = html;
    } catch (error) {
        document.getElementById('peersList').innerHTML = '<div class="peer-item error-text">Failed to load peers</div>';
    }
}

// ============================================================
// MESSAGING FUNCTIONS
// ============================================================

async function sendMessage() {
    const recipientKey = document.getElementById('recipientKey').value.trim();
    const message = document.getElementById('messageText').value.trim();
    const sendBtn = document.getElementById('sendBtn');
    const statusDiv = document.getElementById('sendStatus');
    
    if (!recipientKey || !message) {
        showStatus('Please fill in all fields', 'error');
        return;
    }
    
    sendBtn.disabled = true;
    showStatus('Performing Proof-of-Work (this takes ~5 seconds)...', 'info');
    
    try {
        const data = await apiCall('/api/send', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                recipient_key: recipientKey,
                message: message
            })
        });
        
        if (data.success) {
            showStatus(`Message sent! ID: ${data.message_id.substring(0, 8)}... (${data.solve_time.toFixed(1)}s)`, 'success');
            document.getElementById('messageText').value = '';
            
            // Check message status after a delay
            setTimeout(() => checkMessageStatus(data.message_id), 5000);
        } else {
            showStatus(`Error: ${data.error}`, 'error');
        }
    } catch (error) {
        showStatus(`Error: ${error.message}`, 'error');
    }
    
    sendBtn.disabled = false;
}

async function checkMessageStatus(messageId) {
    try {
        const data = await apiCall(`/api/message/${messageId}/status`);
        if (data.status === 'confirmed') {
            showStatus(`Message ${messageId.substring(0, 8)}... confirmed in block ${data.block_id.substring(0, 8)}...`, 'success');
        }
    } catch (error) {
        // Ignore errors in status check
    }
}

function showStatus(message, type) {
    const statusDiv = document.getElementById('sendStatus');
    statusDiv.textContent = message;
    statusDiv.className = `status-message ${type} show`;
    if (type === 'success' || type === 'error') {
        setTimeout(() => statusDiv.classList.remove('show'), 8000);
    }
}

async function refreshInbox() {
    try {
        const messages = await apiCall('/api/inbox');
        const inboxList = document.getElementById('inboxList');
        
        if (!messages || messages.length === 0) {
            inboxList.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 40px;">No messages yet</div>';
        } else {
            inboxList.innerHTML = messages.map(msg => {
                const statusClass = `status-${msg.status || 'received'}`;
                const statusText = (msg.status || 'received').toUpperCase();
                
                return `
                    <div class="message-item ${msg.read_status ? '' : 'unread'} ${msg.status ? 'status-' + msg.status : ''}" onclick="viewMessage('${msg.message_id}', this)">
                        <div class="message-header">
                            <span>
                                <strong>From:</strong> ${msg.sender_pub_key}
                                <span class="message-status ${statusClass}">${statusText}</span>
                            </span>
                            <span>${new Date(msg.timestamp * 1000).toLocaleString()}</span>
                        </div>
                        <div style="font-size: 14px;">
                            ${msg.read_status ? 'Read' : 'NEW'} - Click to decrypt
                        </div>
                        <div class="message-full" id="msg-${msg.message_id}"></div>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        document.getElementById('inboxList').innerHTML = '<div class="error-text" style="text-align: center; padding: 40px;">Failed to load inbox</div>';
    }
}

async function refreshSentMessages() {
    try {
        const messages = await apiCall('/api/sent');
        const sentList = document.getElementById('sentList');
        
        if (!messages || messages.length === 0) {
            sentList.innerHTML = '<div style="color: #94a3b8; text-align: center; padding: 40px;">No sent messages yet</div>';
        } else {
            sentList.innerHTML = messages.map(msg => {
                const statusClass = `status-${msg.status || 'pending'}`;
                const statusText = (msg.status || 'pending').toUpperCase();
                
                return `
                    <div class="message-item status-${msg.status || 'pending'}" onclick="viewSentMessage('${msg.message_id}', this)">
                        <div class="message-header">
                            <span>
                                <strong>To:</strong> ${msg.recipient_pub_key}
                                <span class="message-status ${statusClass}">${statusText}</span>
                            </span>
                            <span>${new Date(msg.timestamp * 1000).toLocaleString()}</span>
                        </div>
                        <div style="font-size: 14px;">
                            ${msg.preview || 'Encrypted message'}
                        </div>
                        <div class="message-full" id="sent-msg-${msg.message_id}"></div>
                    </div>
                `;
            }).join('');
        }
    } catch (error) {
        document.getElementById('sentList').innerHTML = '<div class="error-text" style="text-align: center; padding: 40px;">Failed to load sent messages</div>';
    }
}

async function viewMessage(messageId, element) {
    const fullDiv = document.getElementById(`msg-${messageId}`);
    
    if (fullDiv.classList.contains('show')) {
        fullDiv.classList.remove('show');
        return;
    }
    
    fullDiv.innerHTML = '<div style="padding: 10px;">Decrypting...</div>';
    fullDiv.classList.add('show');
    
    try {
        const data = await apiCall(`/api/message/${messageId}`);
        
        if (data.error) {
            fullDiv.innerHTML = `<div style="color: #ef4444; padding: 10px;">${data.error}</div>`;
        } else {
            fullDiv.innerHTML = `
                <div style="margin-top: 10px;">
                    <strong>Message:</strong><br>
                    <div style="background: white; padding: 10px; border-radius: 6px; margin-top: 5px; border: 1px solid #e2e8f0;">
                        ${data.plaintext}
                    </div>
                    <small style="color: #64748b;">From: ${data.sender} | Status: ${data.status || 'received'}</small>
                </div>
            `;
            element.classList.remove('unread');
        }
    } catch (error) {
        fullDiv.innerHTML = `<div style="color: #ef4444; padding: 10px;">Failed to decrypt: ${error.message}</div>`;
    }
}

async function viewSentMessage(messageId, element) {
    const fullDiv = document.getElementById(`sent-msg-${messageId}`);
    
    if (fullDiv.classList.contains('show')) {
        fullDiv.classList.remove('show');
        return;
    }
    
    fullDiv.innerHTML = '<div style="padding: 10px;">Loading status...</div>';
    fullDiv.classList.add('show');
    
    try {
        const data = await apiCall(`/api/message/${messageId}/status`);
        
        fullDiv.innerHTML = `
            <div style="margin-top: 10px;">
                <strong>Message Status:</strong><br>
                <div style="background: white; padding: 10px; border-radius: 6px; margin-top: 5px; border: 1px solid #e2e8f0;">
                    <div>Status: <span class="message-status status-${data.status || 'pending'}">${(data.status || 'pending').toUpperCase()}</span></div>
                    ${data.block_id ? `<div>Block: ${data.block_id.substring(0, 16)}...</div>` : '<div>Waiting for confirmation...</div>'}
                    <div>Sent: ${new Date(data.timestamp * 1000).toLocaleString()}</div>
                </div>
            </div>
        `;
    } catch (error) {
        fullDiv.innerHTML = `<div style="color: #ef4444; padding: 10px;">Failed to load status: ${error.message}</div>`;
    }
}

// ============================================================
// INITIALIZATION
// ============================================================

// Load everything on page load
loadAllData();

// Poll for updates
setInterval(loadStatus, 5000);
setInterval(() => {
    if (currentTab === 'inbox') refreshInbox();
    if (currentTab === 'sent') refreshSentMessages();
}, 10000);
setInterval(loadPeers, 15000);
