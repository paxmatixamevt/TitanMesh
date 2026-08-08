#!/usr/bin/env python3
"""
TitanMesh - Decentralized PoW Messaging Protocol
Pure Python implementation with integrated node and messenger UI
No compilation required - works out of the box
"""

import os
import sys
import json
import time
import csv
import hashlib
import threading
import asyncio
import logging
import zipfile
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from collections import defaultdict
import secrets
import base64

# Pure Python crypto - no compilation needed
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad

# Web framework
from flask import Flask, request, jsonify, send_from_directory, send_file, make_response

# HTTP client for broadcasting and sync
import requests

# Async networking - using built-in asyncio
import websockets

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ============================================================================
# TEMPLATE LOADER
# ============================================================================

def get_html_template():
    """Read HTML template from file"""
    template_path = Path(__file__).parent / 'templates' / 'messenger.html'
    if template_path.exists():
        with open(template_path, 'r') as f:
            return f.read()
    else:
        # Fallback minimal template
        return '''<!DOCTYPE html><html><body>
            <h1>TitanMesh Messenger</h1>
            <p>Template file not found. Please create templates/messenger.html</p>
        </body></html>'''

# ============================================================================
# CRYPTOGRAPHY MODULE (Pure Python)
# ============================================================================

class TitanCrypto:
    """Handles all cryptographic operations using pure Python libraries"""
    
    @staticmethod
    def generate_keypair() -> Tuple[str, str]:
        """Generate ECDSA keypair"""
        private_key = SigningKey.generate(curve=SECP256k1)
        public_key = private_key.get_verifying_key()
        return (
            private_key.to_string().hex(),
            public_key.to_string().hex()
        )
    
    @staticmethod
    def get_public_from_private(private_key_hex: str) -> str:
        """Derive public key from private key"""
        private_key = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
        return private_key.get_verifying_key().to_string().hex()
    
    @staticmethod
    def validate_private_key(private_key_hex: str) -> bool:
        """Validate if a string is a valid private key"""
        try:
            private_key = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
            public_key = private_key.get_verifying_key()
            return len(private_key_hex) == 64
        except:
            return False
    
    @staticmethod
    def encrypt_message(plaintext: str, recipient_public_key_hex: str) -> Dict:
        """Encrypt message using ECIES-like scheme with AES"""
        try:
            # Generate ephemeral key
            ephemeral_private = SigningKey.generate(curve=SECP256k1)
            ephemeral_public = ephemeral_private.get_verifying_key()
            
            # Derive shared secret using ECDH
            recipient_public = VerifyingKey.from_string(
                bytes.fromhex(recipient_public_key_hex), curve=SECP256k1
            )
            
            # ECDH: shared_point = ephemeral_private * recipient_public
            shared_point = ephemeral_private.privkey.secret_multiplier * recipient_public.pubkey.point
            
            # Use x-coordinate for key derivation - convert to int first
            x_coord = int(shared_point.x())
            
            # Convert to bytes (32 bytes for secp256k1)
            shared_secret = x_coord.to_bytes(32, 'big')
            
            # Derive AES key using SHA-256
            aes_key = hashlib.sha256(shared_secret).digest()
            
            # Generate random IV
            iv = secrets.token_bytes(16)
            
            # Encrypt with AES-CBC
            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            padded_data = pad(plaintext.encode('utf-8'), AES.block_size)
            ciphertext = cipher.encrypt(padded_data)
            
            return {
                'ephemeral_public_key': ephemeral_public.to_string().hex(),
                'iv': iv.hex(),
                'ciphertext': ciphertext.hex()
            }
        except Exception as e:
            logger.error(f"Encryption error: {e}")
            raise
    
    @staticmethod
    def decrypt_message(encrypted_data: Dict, private_key_hex: str) -> str:
        """Decrypt message using ECIES-like scheme with AES"""
        try:
            # Reconstruct ephemeral public key
            ephemeral_public = VerifyingKey.from_string(
                bytes.fromhex(encrypted_data['ephemeral_public_key']), curve=SECP256k1
            )
            
            # Derive shared secret
            private_key = SigningKey.from_string(bytes.fromhex(private_key_hex), curve=SECP256k1)
            
            # ECDH: shared_point = private_key * ephemeral_public
            shared_point = private_key.privkey.secret_multiplier * ephemeral_public.pubkey.point
            
            # Use x-coordinate for key derivation - convert to int first
            x_coord = int(shared_point.x())
            
            # Convert to bytes (32 bytes for secp256k1)
            shared_secret = x_coord.to_bytes(32, 'big')
            
            # Derive AES key
            aes_key = hashlib.sha256(shared_secret).digest()
            
            # Decrypt
            iv = bytes.fromhex(encrypted_data['iv'])
            ciphertext = bytes.fromhex(encrypted_data['ciphertext'])
            
            cipher = AES.new(aes_key, AES.MODE_CBC, iv)
            padded_data = cipher.decrypt(ciphertext)
            plaintext = unpad(padded_data, AES.block_size)
            
            return plaintext.decode('utf-8')
        except Exception as e:
            logger.error(f"Decryption error: {e}")
            raise

# ============================================================================
# PROOF OF WORK MODULE
# ============================================================================

class ProofOfWork:
    """Handles Proof-of-Work computation and verification"""
    
    @staticmethod
    def solve_pow(data: str, difficulty: int = 4) -> Dict:
        """Solve PoW puzzle"""
        prefix = '0' * difficulty
        nonce = 0
        start_time = time.time()
        
        while True:
            hash_input = f"{data}{nonce}".encode()
            hash_result = hashlib.sha256(hash_input).hexdigest()
            
            if hash_result.startswith(prefix):
                solve_time = time.time() - start_time
                return {
                    'nonce': nonce,
                    'hash': hash_result,
                    'solve_time': solve_time
                }
            
            nonce += 1
    
    @staticmethod
    def verify_pow(data: str, nonce: int, difficulty: int = 4) -> bool:
        """Verify PoW solution"""
        hash_input = f"{data}{nonce}".encode()
        hash_result = hashlib.sha256(hash_input).hexdigest()
        return hash_result.startswith('0' * difficulty)

# ============================================================================
# STORAGE MODULE
# ============================================================================

class Storage:
    """JSON-based storage system"""
    
    def __init__(self, node_id: str, data_dir: str = "data"):
        self.node_id = node_id
        self.data_dir = Path(data_dir) / node_id
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        self.blocks_file = self.data_dir / "blocks.json"
        self.messages_file = self.data_dir / "messages.json"
        self.state_file = self.data_dir / "state.json"
        self.inbox_file = self.data_dir / "inbox.json"
        self.peers_file = self.data_dir / "peers.json"
        self.sent_file = self.data_dir / "sent.json"
        
        # Initialize storage
        self.blocks = self._load_json(self.blocks_file, [])
        self.messages = self._load_json(self.messages_file, [])
        self.state_table = self._load_json(self.state_file, {})
        self.inbox = self._load_json(self.inbox_file, [])
        self.peers = self._load_json(self.peers_file, [])
        self.sent_messages = self._load_json(self.sent_file, [])
        
        # Auto-save thread
        self._start_auto_save()
    
    def _load_json(self, file_path: Path, default: any) -> any:
        """Load data from JSON file"""
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading {file_path}: {e}")
        return default
    
    def _save_json(self, file_path: Path, data: any):
        """Save data to JSON file"""
        try:
            with open(file_path, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Error saving {file_path}: {e}")
    
    def _start_auto_save(self):
        """Start periodic auto-save"""
        def auto_save():
            while True:
                time.sleep(30)
                self.save_all()
        
        thread = threading.Thread(target=auto_save, daemon=True)
        thread.start()
    
    def save_all(self):
        """Save all data to disk"""
        self._save_json(self.blocks_file, self.blocks[-1000:])
        self._save_json(self.messages_file, self.messages[-5000:])
        self._save_json(self.state_file, self.state_table)
        self._save_json(self.inbox_file, self.inbox[-500:])
        self._save_json(self.peers_file, self.peers)
        self._save_json(self.sent_file, self.sent_messages[-500:])
    
    # Block operations
    def add_block(self, block: Dict) -> bool:
        """Add a block with consensus rules: only accept if longer chain or bigger timestamp"""
        # Check if block already exists
        existing = next((b for b in self.blocks if b['block_id'] == block['block_id']), None)
        if existing:
            return False
        
        # Check if this block is part of a longer chain or has bigger timestamp
        block_number = block.get('block_number', 0)
        block_timestamp = block.get('timestamp', 0)
        
        # Find the current block at this height
        existing_at_height = next((b for b in self.blocks if b.get('block_number') == block_number), None)
        
        if existing_at_height:
            # If same height, accept the one with bigger timestamp
            if block_timestamp <= existing_at_height.get('timestamp', 0):
                logger.debug(f"Block at height {block_number} has older timestamp, rejecting")
                return False
            
            # Remove the old block at this height and any blocks after it
            logger.info(f"Replacing block at height {block_number} with newer timestamp")
            self.blocks = [b for b in self.blocks if b.get('block_number', 0) < block_number]
        
        # Check if this extends the chain (or is a longer chain)
        if block_number > 0:
            prev_block = next((b for b in self.blocks if b.get('block_number') == block_number - 1), None)
            if prev_block and prev_block['block_id'] != block.get('prev_hash'):
                # This might be a fork - check if the fork is longer
                # For simplicity, we'll accept the longer chain
                # The height check below handles this
                pass
        
        # Add the block
        self.blocks.append(block)
        self.blocks.sort(key=lambda x: x.get('block_number', 0))
        
        # If this block has a higher number than our latest, update statuses
        if block_number >= len(self.blocks) - 1:
            for msg in block.get('messages', []):
                self.update_message_status(msg['message_id'], 'confirmed', block['block_id'])
        
        logger.info(f"Block {block['block_id'][:8]} added at height {block_number}")
        return True
    
    def get_latest_block(self) -> Optional[Dict]:
        return self.blocks[-1] if self.blocks else None
    
    def get_block(self, block_id: str) -> Optional[Dict]:
        for block in self.blocks:
            if block['block_id'] == block_id:
                return block
        return None
    
    def get_blocks_range(self, start: int, end: int) -> List[Dict]:
        """Get blocks in a range of block numbers"""
        return [b for b in self.blocks if start <= b.get('block_number', 0) <= end]
    
    def get_block_count(self) -> int:
        return len(self.blocks)
    
    def get_block_by_number(self, number: int) -> Optional[Dict]:
        """Get block by number"""
        for block in self.blocks:
            if block.get('block_number') == number:
                return block
        return None
    
    def get_blockchain_height(self) -> int:
        """Get the current blockchain height"""
        return self.blocks[-1].get('block_number', -1) if self.blocks else -1
    
    # Message operations
    def add_message(self, message: Dict) -> bool:
        if not any(m['message_id'] == message['message_id'] for m in self.messages):
            self.messages.append(message)
            return True
        return False
    
    def get_pending_messages(self) -> List[Dict]:
        return [m for m in self.messages if m.get('status') == 'pending']
    
    def update_message_status(self, message_id: str, status: str, block_id: str = None):
        for message in self.messages:
            if message['message_id'] == message_id:
                message['status'] = status
                if block_id:
                    message['block_id'] = block_id
                break
        
        # Also update in sent messages
        for msg in self.sent_messages:
            if msg['message_id'] == message_id:
                msg['status'] = status
                if block_id:
                    msg['block_id'] = block_id
                break
        
        # Also update in inbox
        for msg in self.inbox:
            if msg['message_id'] == message_id:
                msg['status'] = status
                if block_id:
                    msg['block_id'] = block_id
                break
    
    def get_message_count(self) -> int:
        return len(self.messages)
    
    def get_message_by_id(self, message_id: str) -> Optional[Dict]:
        """Get a specific message by ID"""
        for msg in self.messages:
            if msg['message_id'] == message_id:
                return msg
        for msg in self.sent_messages:
            if msg['message_id'] == message_id:
                return msg
        return None
    
    # State table operations
    def update_nonce(self, sender_pub_key: str, nonce: int):
        self.state_table[sender_pub_key] = {
            'last_nonce': nonce,
            'last_seen': int(time.time())
        }
    
    def get_nonce(self, sender_pub_key: str) -> int:
        return self.state_table.get(sender_pub_key, {}).get('last_nonce', -1)
    
    # Inbox operations
    def add_to_inbox(self, message: Dict) -> bool:
        if not any(m['message_id'] == message['message_id'] for m in self.inbox):
            self.inbox.append({
                **message,
                'read_status': False,
                'received_at': int(time.time()),
                'status': 'received'
            })
            return True
        return False
    
    def get_inbox(self) -> List[Dict]:
        return sorted(self.inbox, key=lambda x: x.get('timestamp', 0), reverse=True)
    
    def mark_as_read(self, message_id: str):
        for message in self.inbox:
            if message['message_id'] == message_id:
                message['read_status'] = True
                break
    
    def get_inbox_count(self) -> int:
        return len(self.inbox)
    
    def get_unread_count(self) -> int:
        return len([m for m in self.inbox if not m.get('read_status')])
    
    # Sent messages operations
    def add_sent_message(self, message: Dict):
        """Add a message to sent messages tracking"""
        if not any(m['message_id'] == message['message_id'] for m in self.sent_messages):
            self.sent_messages.append({
                **message,
                'sent_at': int(time.time()),
                'status': 'pending'
            })
    
    def get_sent_messages(self) -> List[Dict]:
        """Get all sent messages"""
        return sorted(self.sent_messages, key=lambda x: x.get('timestamp', 0), reverse=True)
    
    # Peer management
    def add_peer(self, peer: Dict):
        existing = next((p for p in self.peers if p['node_id'] == peer['node_id']), None)
        if existing:
            existing.update(peer)
            existing['last_seen'] = int(time.time())
        else:
            self.peers.append({
                **peer,
                'last_seen': int(time.time()),
                'reputation': 1.0
            })
    
    def get_peers(self) -> List[Dict]:
        return sorted(self.peers, key=lambda x: x.get('last_seen', 0), reverse=True)[:100]
    
    # Data export
    def export_all_data(self) -> Dict:
        """Export all data for backup"""
        return {
            'node_id': self.node_id,
            'export_time': int(time.time()),
            'blocks': self.blocks,
            'messages': self.messages,
            'sent_messages': self.sent_messages,
            'inbox': self.inbox,
            'state_table': self.state_table,
            'peers': self.peers
        }
    
    def import_data(self, data: Dict):
        """Import data from backup"""
        try:
            if 'blocks' in data:
                for block in data['blocks']:
                    self.add_block(block)
            
            if 'messages' in data:
                for msg in data['messages']:
                    self.add_message(msg)
            
            if 'sent_messages' in data:
                for msg in data['sent_messages']:
                    if not any(m['message_id'] == msg['message_id'] for m in self.sent_messages):
                        self.sent_messages.append(msg)
            
            if 'inbox' in data:
                for msg in data['inbox']:
                    self.add_to_inbox(msg)
            
            if 'state_table' in data:
                self.state_table.update(data['state_table'])
            
            if 'peers' in data:
                for peer in data['peers']:
                    self.add_peer(peer)
            
            return True
        except Exception as e:
            logger.error(f"Error importing data: {e}")
            return False
    
    # Cleanup
    def prune_old_blocks(self, days: int = 30):
        cutoff = int(time.time()) - (days * 86400)
        original_len = len(self.blocks)
        self.blocks = [b for b in self.blocks if b.get('timestamp', 0) > cutoff]
        
        self.messages = [
            m for m in self.messages 
            if not (m.get('status') == 'confirmed' and m.get('timestamp', 0) < cutoff)
        ]
        
        pruned = original_len - len(self.blocks)
        if pruned > 0:
            logger.info(f"Pruned {pruned} old blocks")
    
    def close(self):
        self.save_all()
        logger.info("Storage closed")

# ============================================================================
# BLOCK MODULE
# ============================================================================

class Block:
    """Block creation and validation"""
    
    @staticmethod
    def create_merkle_tree(messages: List[Dict]) -> str:
        """Create Merkle tree and return root hash"""
        if not messages:
            return hashlib.sha256(b'empty').hexdigest()
        
        leaves = []
        for msg in messages:
            data = f"{msg['message_id']}{msg['sender_pub_key']}{msg['recipient_stealth']}{msg['timestamp']}"
            leaves.append(hashlib.sha256(data.encode()).hexdigest())
        
        while len(leaves) > 1:
            if len(leaves) % 2 == 1:
                leaves.append(leaves[-1])
            
            new_leaves = []
            for i in range(0, len(leaves), 2):
                combined = leaves[i] + leaves[i + 1]
                new_leaves.append(hashlib.sha256(combined.encode()).hexdigest())
            
            leaves = new_leaves
        
        return leaves[0] if leaves else hashlib.sha256(b'empty').hexdigest()
    
    @staticmethod
    def create_block(messages: List[Dict], prev_hash: str, miner_id: str) -> Dict:
        """Create a new block"""
        block_number = 0  # Will be set by miner
        timestamp = int(time.time())
        merkle_root = Block.create_merkle_tree(messages)
        
        block_data = f"{block_number}{prev_hash}{merkle_root}{timestamp}{miner_id}"
        pow_result = ProofOfWork.solve_pow(block_data, difficulty=1)
        
        block = {
            'block_id': pow_result['hash'],
            'block_number': block_number,
            'prev_hash': prev_hash,
            'merkle_root': merkle_root,
            'timestamp': timestamp,
            'pow_nonce': pow_result['nonce'],
            'miner_id': miner_id,
            'messages': messages
        }
        
        return block
    
    @staticmethod
    def validate_block(block: Dict) -> bool:
        """Validate a block"""
        if not all(k in block for k in ['block_number', 'prev_hash', 'merkle_root', 'timestamp', 'miner_id', 'pow_nonce']):
            return False
        
        block_data = f"{block['block_number']}{block['prev_hash']}{block['merkle_root']}{block['timestamp']}{block['miner_id']}"
        if not ProofOfWork.verify_pow(block_data, block['pow_nonce'], difficulty=1):
            return False
        
        calculated_root = Block.create_merkle_tree(block.get('messages', []))
        return calculated_root == block['merkle_root']

# ============================================================================
# P2P NETWORK MODULE
# ============================================================================

class P2PNetwork:
    """Peer-to-peer networking using pure Python websockets"""
    
    def __init__(self, node_id: str, port: int, storage: Storage, node_instance):
        self.node_id = node_id
        self.port = port
        self.storage = storage
        self.node = node_instance
        self.connected_peers: Dict[str, any] = {}
        self.server = None
        self.message_queue = asyncio.Queue()
        self.broadcast_lock = asyncio.Lock()
    
    async def handle_connection(self, websocket):
        """Handle incoming WebSocket connection"""
        peer_id = secrets.token_hex(8)
        self.connected_peers[peer_id] = websocket
        logger.info(f"New WebSocket connection: {peer_id[:8]}")
        
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                    await self.handle_message(peer_id, data)
                except Exception as e:
                    logger.error(f"Error handling message: {e}")
        except Exception as e:
            logger.debug(f"Connection closed: {e}")
        finally:
            if peer_id in self.connected_peers:
                del self.connected_peers[peer_id]
                logger.info(f"WebSocket disconnected: {peer_id[:8]}")
    
    async def handle_message(self, peer_id: str, message: Dict):
        """Process incoming messages"""
        msg_type = message.get('type')
        
        if msg_type == 'HANDSHAKE':
            await self.handle_handshake(peer_id, message)
        elif msg_type == 'NEW_MESSAGE':
            await self.handle_new_message(peer_id, message)
        elif msg_type == 'NEW_BLOCK':
            await self.handle_new_block(peer_id, message)
        elif msg_type == 'REQUEST_PEERS':
            await self.handle_peer_request(peer_id, message)
        elif msg_type == 'REQUEST_SYNC':
            await self.handle_sync_request(peer_id, message)
    
    async def handle_handshake(self, peer_id: str, message: Dict):
        """Handle peer handshake"""
        logger.info(f"Handshake from node: {message.get('node_id')}")
        ws = self.connected_peers.get(peer_id)
        if ws:
            latest_block = self.storage.get_latest_block()
            await ws.send(json.dumps({
                'type': 'SYNC_INFO',
                'node_id': self.node_id,
                'block_height': latest_block['block_number'] if latest_block else -1,
                'block_count': self.storage.get_block_count()
            }))
    
    async def handle_new_message(self, peer_id: str, message: Dict):
        """Handle new message from peer - broadcast to all other connected peers"""
        msg_data = message.get('message_data', {})
        
        # Process the message
        await self.node._receive_message_async(msg_data)
        
        # Broadcast to all other connected peers (except the one who sent it)
        await self._broadcast_to_peers('NEW_MESSAGE', {'message_data': msg_data}, exclude_peer_id=peer_id)
    
    async def handle_new_block(self, peer_id: str, message: Dict):
        """Handle new block from peer - broadcast to all other connected peers"""
        block = message.get('block', {})
        
        if not Block.validate_block(block):
            logger.warning("Invalid block received via WebSocket")
            return
        
        # Try to add the block (consensus rules apply)
        if self.storage.add_block(block):
            for msg in block.get('messages', []):
                self.storage.update_message_status(msg['message_id'], 'confirmed', block['block_id'])
            
            await self.node.scan_for_messages(block)
            
            # Broadcast to all other connected peers (except the one who sent it)
            await self._broadcast_to_peers('NEW_BLOCK', {'block': block}, exclude_peer_id=peer_id)
            
            logger.info(f"Block {block['block_id'][:8]} added via WebSocket")
        else:
            # Check if this block has higher timestamp than existing at same height
            existing = self.storage.get_block_by_number(block.get('block_number', 0))
            if existing and block.get('timestamp', 0) > existing.get('timestamp', 0):
                logger.info(f"Received newer block at height {block.get('block_number')}, re-validating chain")
                # Re-validate and potentially replace
                if self.storage.add_block(block):
                    await self._broadcast_to_peers('NEW_BLOCK', {'block': block}, exclude_peer_id=peer_id)
    
    async def _broadcast_to_peers(self, msg_type: str, data: Dict, exclude_peer_id: str = None):
        """Broadcast a message to all connected peers except the excluded one"""
        async with self.broadcast_lock:
            # Get list of peers to broadcast to (excluding the sender)
            peers_to_send = [
                (pid, ws) for pid, ws in self.connected_peers.items()
                if pid != exclude_peer_id
            ]
            
            if not peers_to_send:
                return
            
            # Create the message once
            broadcast_msg = json.dumps({
                'type': msg_type,
                **data
            })
            
            # Send to all peers in parallel
            tasks = []
            for peer_id, ws in peers_to_send:
                try:
                    tasks.append(ws.send(broadcast_msg))
                except Exception as e:
                    logger.error(f"Error preparing broadcast to {peer_id}: {e}")
            
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
    
    async def handle_peer_request(self, peer_id: str, message: Dict):
        """Handle peer list request"""
        peers = self.storage.get_peers()
        ws = self.connected_peers.get(peer_id)
        if ws:
            await ws.send(json.dumps({
                'type': 'PEER_LIST',
                'peers': peers
            }))
    
    async def handle_sync_request(self, peer_id: str, message: Dict):
        """Handle sync request from peer"""
        start = message.get('start', 0)
        end = message.get('end', -1)
        
        blocks = self.storage.get_blocks_range(start, end)
        ws = self.connected_peers.get(peer_id)
        if ws:
            await ws.send(json.dumps({
                'type': 'SYNC_RESPONSE',
                'blocks': blocks,
                'total': self.storage.get_block_count()
            }))
    
    async def connect_to_peer(self, address: str, port: int):
        """Connect to a peer"""
        try:
            uri = f"ws://{address}:{port}"
            logger.info(f"Attempting WebSocket connection to {uri}")
            async with websockets.connect(uri, ping_interval=None, close_timeout=5) as websocket:
                peer_id = secrets.token_hex(8)
                self.connected_peers[peer_id] = websocket
                logger.info(f"Connected to peer at {address}:{port}")
                
                # Send handshake
                await websocket.send(json.dumps({
                    'type': 'HANDSHAKE',
                    'node_id': self.node_id,
                    'port': self.port
                }))
                
                # Listen for messages
                async for message in websocket:
                    try:
                        data = json.loads(message)
                        await self.handle_message(peer_id, data)
                    except Exception as e:
                        logger.error(f"Error handling peer message: {e}")
        
        except asyncio.TimeoutError:
            logger.debug(f"Connection timeout to {address}:{port}")
        except Exception as e:
            logger.debug(f"Could not connect to peer {address}:{port}: {e}")
    
    async def start(self):
        """Start P2P network"""
        try:
            self.server = await websockets.serve(
                self.handle_connection, "0.0.0.0", self.port,
                ping_interval=None,
                close_timeout=5
            )
            logger.info(f"P2P WebSocket server started on port {self.port}")
        except Exception as e:
            logger.error(f"Failed to start P2P server: {e}")
    
    def get_connected_peers(self) -> List[str]:
        """Get list of connected peer IDs"""
        return list(self.connected_peers.keys())

# ============================================================================
# MINER MODULE
# ============================================================================

class Miner:
    """Block mining and creation"""
    
    def __init__(self, node_instance):
        self.node = node_instance
        self.mining = False
        self.mining_thread = None
    
    def should_mine(self) -> bool:
        """Deterministic miner selection"""
        latest_block = self.node.storage.get_latest_block()
        if not latest_block:
            return True
        
        prev_hash = latest_block['block_id']
        peer_count = max(1, len(self.node.p2p.connected_peers) + 1)
        
        current_slot = int(time.time() / 10)
        selection_data = f"{prev_hash}{current_slot}"
        hash_val = hashlib.sha256(selection_data.encode()).hexdigest()
        selected_index = int(hash_val[:8], 16) % peer_count
        
        try:
            our_index = int(self.node.node_id[:8], 16) % peer_count
        except ValueError:
            our_index = hash(self.node.node_id) % peer_count
        
        return selected_index == our_index
    
    def start_mining(self):
        """Start mining process"""
        self.mining = True
        self.mining_thread = threading.Thread(target=self._mine_loop, daemon=True)
        self.mining_thread.start()
        logger.info("Miner started")
    
    def _mine_loop(self):
        """Mining loop"""
        while self.mining:
            try:
                if self.should_mine():
                    self._mine_block()
            except Exception as e:
                logger.error(f"Mining loop error: {e}")
            time.sleep(10)
    
    def _mine_block(self):
        """Mine a new block"""
        try:
            pending_messages = self.node.storage.get_pending_messages()
            
            if not pending_messages:
                return
            
            latest_block = self.node.storage.get_latest_block()
            prev_hash = latest_block['block_id'] if latest_block else '0' * 64
            block_number = (latest_block['block_number'] + 1) if latest_block else 0
            
            # Create block with proper block number
            block = Block.create_block(pending_messages, prev_hash, self.node.node_id)
            block['block_number'] = block_number
            
            # Add block locally (consensus rules apply)
            if self.node.storage.add_block(block):
                # Update message statuses
                for msg in pending_messages:
                    self.node.storage.update_message_status(msg['message_id'], 'confirmed', block['block_id'])
                
                # Broadcast block via HTTP
                self.node._broadcast_block_http(block)
                
                # Broadcast via WebSocket to all connected peers
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.node.p2p._broadcast_to_peers('NEW_BLOCK', {'block': block}))
                except RuntimeError:
                    pass
                
                logger.info(f"Block {block['block_id'][:8]} mined (#{block_number}) with {len(pending_messages)} messages")
            
        except Exception as e:
            logger.error(f"Mining error: {e}")
    
    def stop_mining(self):
        """Stop mining"""
        self.mining = False
        logger.info("Miner stopped")

# ============================================================================
# MAIN NODE APPLICATION
# ============================================================================

class TitanNode:
    """Main TitanMesh node with integrated messenger"""
    
    def __init__(self, node_id: str = None, port: int = 5000, peers_file: str = "nodes.csv"):
        self.node_id = node_id or secrets.token_hex(8)
        self.port = port
        self.api_port = port + 1
        self.peers_file = peers_file
        
        # Initialize components
        self.storage = Storage(self.node_id)
        self.p2p = P2PNetwork(self.node_id, port, self.storage, self)
        self.miner = Miner(self)
        
        # No keys stored in node - users must generate and provide their own
        self.keys = None
        
        # Track seen messages to prevent loops
        self.seen_messages = set()
        self.seen_blocks = set()
        
        # Flask app for web UI
        self.app = Flask(__name__)
        self.app.secret_key = secrets.token_hex(16)
        
        # Setup routes
        self._setup_routes()
        
        logger.info(f"TitanMesh Node {self.node_id[:8]} initialized")
        logger.info(f"API Port: {self.api_port}, P2P Port: {self.port}")
        logger.info("No keys loaded - users must generate or import keys")
    
    def _setup_routes(self):
        """Setup Flask routes"""
        
        @self.app.route('/')
        def index():
            return get_html_template()
        
        @self.app.route('/static/<path:filename>')
        def serve_static(filename):
            static_dir = Path(__file__).parent / 'static'
            return send_from_directory(static_dir, filename)
        
        # =====================================================================
        # KEY MANAGEMENT APIS - No keys stored on node
        # =====================================================================
        
        @self.app.route('/api/keys/generate', methods=['POST'])
        def generate_keys():
            """Generate a new keypair for the client"""
            try:
                private_key, public_key = TitanCrypto.generate_keypair()
                return jsonify({
                    'success': True,
                    'private_key': private_key,
                    'public_key': public_key,
                    'message': 'Keep your private key safe! It will not be stored on the node.'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/keys/validate', methods=['POST'])
        def validate_keys():
            """Validate a private key"""
            try:
                data = request.json
                private_key = data.get('private_key')
                
                if not private_key:
                    return jsonify({'error': 'No private key provided'}), 400
                
                is_valid = TitanCrypto.validate_private_key(private_key)
                
                if is_valid:
                    public_key = TitanCrypto.get_public_from_private(private_key)
                    return jsonify({
                        'valid': True,
                        'public_key': public_key
                    })
                else:
                    return jsonify({
                        'valid': False,
                        'message': 'Invalid private key format'
                    })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/keys/derive', methods=['POST'])
        def derive_public_key():
            """Derive public key from private key"""
            try:
                data = request.json
                private_key = data.get('private_key')
                
                if not private_key:
                    return jsonify({'error': 'No private key provided'}), 400
                
                public_key = TitanCrypto.get_public_from_private(private_key)
                return jsonify({
                    'success': True,
                    'public_key': public_key
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        # =====================================================================
        # SESSION MANAGEMENT - Keys are session-based, not stored
        # =====================================================================
        
        @self.app.route('/api/session/set_keys', methods=['POST'])
        def set_session_keys():
            """Set keys for the current session (stored in memory only)"""
            try:
                data = request.json
                private_key = data.get('private_key')
                
                if not private_key:
                    return jsonify({'error': 'No private key provided'}), 400
                
                if not TitanCrypto.validate_private_key(private_key):
                    return jsonify({'error': 'Invalid private key'}), 400
                
                public_key = TitanCrypto.get_public_from_private(private_key)
                
                # Store keys in memory only (not persisted)
                self.keys = {
                    'private_key': private_key,
                    'public_key': public_key
                }
                
                return jsonify({
                    'success': True,
                    'public_key': public_key,
                    'message': 'Keys set for this session'
                })
            except Exception as e:
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/session/clear_keys', methods=['POST'])
        def clear_session_keys():
            """Clear session keys"""
            self.keys = None
            return jsonify({
                'success': True,
                'message': 'Keys cleared from session'
            })
        
        @self.app.route('/api/session/status')
        def session_status():
            """Check if keys are set in the current session"""
            return jsonify({
                'has_keys': self.keys is not None,
                'public_key': self.keys.get('public_key') if self.keys else None
            })
        
        # =====================================================================
        # NODE STATUS APIS
        # =====================================================================
        
        @self.app.route('/api/status')
        def status():
            latest_block = self.storage.get_latest_block()
            return jsonify({
                'node_id': self.node_id,
                'has_keys': self.keys is not None,
                'public_key': self.keys.get('public_key') if self.keys else None,
                'peers': len(self.p2p.connected_peers),
                'known_peers': len(self.storage.get_peers()),
                'latest_block': latest_block['block_number'] if latest_block else -1,
                'total_blocks': self.storage.get_block_count(),
                'total_messages': self.storage.get_message_count(),
                'pending_messages': len(self.storage.get_pending_messages()),
                'inbox_count': self.storage.get_inbox_count(),
                'unread_count': self.storage.get_unread_count(),
                'sent_count': len(self.storage.sent_messages),
                'uptime': time.time()
            })
        
        @self.app.route('/api/peers')
        def get_peers():
            csv_peers = []
            if os.path.exists(self.peers_file):
                with open(self.peers_file, 'r') as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        csv_peers.append(row)
            
            stored_peers = self.storage.get_peers()
            
            connected = []
            for peer_id in self.p2p.connected_peers:
                connected.append({
                    'peer_id': peer_id[:8],
                    'status': 'connected'
                })
            
            return jsonify({
                'known_peers': csv_peers,
                'stored_peers': stored_peers,
                'connected_peers': connected,
                'our_node_id': self.node_id,
                'our_api_port': self.api_port,
                'our_p2p_port': self.port
            })
        
        @self.app.route('/api/blocks')
        def get_blocks():
            start = request.args.get('start', 0, type=int)
            end = request.args.get('end', None, type=int)
            
            if end is None:
                end = self.storage.get_block_count() - 1
            
            blocks = self.storage.get_blocks_range(start, end)
            
            return jsonify({
                'blocks': blocks,
                'total': self.storage.get_block_count(),
                'start': start,
                'end': end,
                'returned': len(blocks)
            })
        
        @self.app.route('/api/sync_status')
        def sync_status():
            latest = self.storage.get_latest_block()
            return jsonify({
                'node_id': self.node_id,
                'block_height': latest['block_number'] if latest else -1,
                'total_blocks': self.storage.get_block_count(),
                'total_messages': self.storage.get_message_count(),
                'peers': len(self.storage.get_peers()),
                'connected': len(self.p2p.connected_peers)
            })
        
        # =====================================================================
        # INBOX AND MESSAGE APIS
        # =====================================================================
        
        @self.app.route('/api/inbox')
        def get_inbox():
            messages = self.storage.get_inbox()
            return jsonify([{
                'message_id': m['message_id'],
                'sender_pub_key': m.get('sender_pub_key', '')[:16] + '...',
                'timestamp': m.get('timestamp', 0),
                'read_status': m.get('read_status', False),
                'status': m.get('status', 'received'),
                'preview': 'Encrypted message'
            } for m in messages])
        
        @self.app.route('/api/sent')
        def get_sent_messages():
            """Get all sent messages"""
            messages = self.storage.get_sent_messages()
            return jsonify([{
                'message_id': m['message_id'],
                'recipient_pub_key': m.get('recipient_stealth', '')[:16] + '...',
                'timestamp': m.get('timestamp', 0),
                'status': m.get('status', 'unknown'),
                'block_id': m.get('block_id', ''),
                'preview': m.get('plaintext_preview', 'Encrypted message')
            } for m in messages])
        
        @self.app.route('/api/message/<message_id>')
        def get_message(message_id):
            """Get and decrypt a message - requires session keys"""
            if not self.keys:
                return jsonify({'error': 'No keys set in session. Please set your keys first.'}), 401
            
            message = None
            for m in self.storage.inbox:
                if m['message_id'] == message_id:
                    message = m
                    break
            
            if not message:
                return jsonify({'error': 'Message not found'}), 404
            
            try:
                encrypted_data = {
                    'ephemeral_public_key': message['ephemeral_public_key'],
                    'iv': message['iv'],
                    'ciphertext': message['encrypted_text']
                }
                
                decrypted = TitanCrypto.decrypt_message(encrypted_data, self.keys['private_key'])
                self.storage.mark_as_read(message_id)
                
                return jsonify({
                    'message_id': message['message_id'],
                    'sender': message.get('sender_pub_key', ''),
                    'timestamp': message.get('timestamp', 0),
                    'plaintext': decrypted,
                    'read_status': True,
                    'status': message.get('status', 'received')
                })
            except Exception as e:
                logger.error(f"Decryption failed: {e}")
                return jsonify({'error': f'Decryption failed: {str(e)}'}), 500
        
        @self.app.route('/api/message/<message_id>/status')
        def get_message_status(message_id):
            """Get the status of a specific message"""
            message = self.storage.get_message_by_id(message_id)
            
            if not message:
                return jsonify({'error': 'Message not found'}), 404
            
            return jsonify({
                'message_id': message['message_id'],
                'status': message.get('status', 'unknown'),
                'block_id': message.get('block_id', ''),
                'timestamp': message.get('timestamp', 0)
            })
        
        @self.app.route('/api/send', methods=['POST'])
        def send_message():
            """Send a message - requires session keys"""
            if not self.keys:
                return jsonify({'error': 'No keys set in session. Please set your keys first.'}), 401
            
            data = request.json
            recipient_pub_key = data.get('recipient_key')
            plaintext = data.get('message')
            
            if not recipient_pub_key or not plaintext:
                return jsonify({'error': 'Missing recipient or message'}), 400
            
            try:
                sender_public_key = self.keys['public_key']
                
                # Encrypt message
                encrypted = TitanCrypto.encrypt_message(plaintext, recipient_pub_key)
                
                # Create message packet
                message_id = secrets.token_hex(16)
                nonce = int(time.time() * 1000)
                timestamp = int(time.time())
                
                message_data = {
                    'message_id': message_id,
                    'sender_pub_key': sender_public_key,
                    'recipient_stealth': recipient_pub_key,
                    'encrypted_text': encrypted['ciphertext'],
                    'ephemeral_public_key': encrypted['ephemeral_public_key'],
                    'iv': encrypted['iv'],
                    'nonce': nonce,
                    'timestamp': timestamp,
                    'pow_nonce': 0,
                    'plaintext_preview': plaintext[:50] + ('...' if len(plaintext) > 50 else '')
                }
                
                # Perform Proof-of-Work
                pow_data = f"{message_data['sender_pub_key']}{message_data['recipient_stealth']}{message_data['encrypted_text']}{message_data['nonce']}{message_data['timestamp']}"
                
                logger.info(f"Starting PoW for message {message_id[:8]}...")
                pow_result = ProofOfWork.solve_pow(pow_data, difficulty=4)
                message_data['pow_nonce'] = pow_result['nonce']
                logger.info(f"PoW complete in {pow_result['solve_time']:.2f}s")
                
                # Add to local storage
                message_data['status'] = 'pending'
                self.storage.add_message(message_data)
                
                # Add to sent messages
                self.storage.add_sent_message(message_data)
                
                # Check if sending to self
                if recipient_pub_key == self.keys['public_key']:
                    logger.info("Self-message detected, adding to inbox directly")
                    inbox_msg = {
                        'message_id': message_id,
                        'sender_pub_key': sender_public_key,
                        'encrypted_text': encrypted['ciphertext'],
                        'ephemeral_public_key': encrypted['ephemeral_public_key'],
                        'iv': encrypted['iv'],
                        'timestamp': timestamp,
                        'block_id': 'self',
                        'status': 'confirmed'
                    }
                    self.storage.add_to_inbox(inbox_msg)
                    self.storage.update_message_status(message_id, 'confirmed', 'self')
                
                # Track seen message
                self.seen_messages.add(message_id)
                
                # Broadcast message to all known peers via HTTP
                logger.info(f"Broadcasting message {message_id[:8]} to peers")
                self._broadcast_message_http(message_data)
                
                # Also gossip via WebSocket to all connected peers
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.p2p._broadcast_to_peers('NEW_MESSAGE', {'message_data': message_data}))
                except RuntimeError:
                    pass
                
                return jsonify({
                    'success': True,
                    'message_id': message_id,
                    'solve_time': pow_result['solve_time']
                })
                
            except Exception as e:
                logger.error(f"Send error: {e}")
                return jsonify({'error': str(e)}), 500
        
        @self.app.route('/api/receive_message', methods=['POST'])
        def receive_message():
            """Receive message from another node via HTTP"""
            message_data = request.json
            if not message_data:
                return jsonify({'error': 'No data'}), 400
            
            logger.info(f"Received message via HTTP: {message_data.get('message_id', 'unknown')[:8]}")
            
            # Process the message and broadcast to peers
            success = self._receive_message(message_data)
            
            # Broadcast to all peers via HTTP as well
            if success:
                # HTTP broadcast to peers (excluding the one that sent it)
                threading.Thread(target=self._broadcast_message_http, args=(message_data,), daemon=True).start()
                
                # WebSocket broadcast
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.p2p._broadcast_to_peers('NEW_MESSAGE', {'message_data': message_data}))
                except RuntimeError:
                    pass
            
            if success:
                return jsonify({'status': 'ok'})
            else:
                return jsonify({'status': 'rejected'}), 400
        
        @self.app.route('/api/receive_block', methods=['POST'])
        def receive_block():
            """Receive block from another node via HTTP"""
            block_data = request.json
            if not block_data:
                return jsonify({'error': 'No data'}), 400
            
            logger.info(f"Received block via HTTP: {block_data.get('block_id', 'unknown')[:8]}")
            
            success = self._receive_block(block_data)
            
            if success:
                # Broadcast to all peers via HTTP as well
                threading.Thread(target=self._broadcast_block_http, args=(block_data,), daemon=True).start()
                
                # WebSocket broadcast
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.p2p._broadcast_to_peers('NEW_BLOCK', {'block': block_data}))
                except RuntimeError:
                    pass
            
            if success:
                return jsonify({'status': 'ok'})
            else:
                return jsonify({'status': 'rejected'}), 400
        
        @self.app.route('/api/debug/inbox')
        def debug_inbox():
            """Debug endpoint to see raw inbox data"""
            return jsonify({
                'inbox_count': len(self.storage.inbox),
                'inbox': [{
                    'message_id': m['message_id'][:8],
                    'sender': m.get('sender_pub_key', '')[:16],
                    'timestamp': m.get('timestamp', 0),
                    'has_encrypted': 'encrypted_text' in m,
                    'status': m.get('status', 'received')
                } for m in self.storage.inbox]
            })
        
        @self.app.route('/api/debug/sent')
        def debug_sent():
            """Debug endpoint to see raw sent messages data"""
            return jsonify({
                'sent_count': len(self.storage.sent_messages),
                'sent_messages': [{
                    'message_id': m['message_id'][:8],
                    'recipient': m.get('recipient_stealth', '')[:16],
                    'timestamp': m.get('timestamp', 0),
                    'status': m.get('status', 'unknown'),
                    'block_id': m.get('block_id', '')[:8]
                } for m in self.storage.sent_messages]
            })
    
    async def _receive_message_async(self, message_data: Dict) -> bool:
        """Async version of receive message"""
        return self._receive_message(message_data)
    
    def _receive_message(self, message_data: Dict) -> bool:
        """Process received message"""
        try:
            message_id = message_data.get('message_id', 'unknown')
            logger.info(f"Processing received message: {message_id[:8]}")
            
            # Check if we've already seen this message (prevent loops)
            if message_id in self.seen_messages:
                logger.debug(f"Message {message_id[:8]} already seen, skipping")
                return True
            
            # Verify PoW
            pow_data = f"{message_data['sender_pub_key']}{message_data['recipient_stealth']}{message_data['encrypted_text']}{message_data['nonce']}{message_data['timestamp']}"
            if not ProofOfWork.verify_pow(pow_data, message_data['pow_nonce']):
                logger.warning("Invalid PoW on received message")
                return False
            
            # Check nonce
            last_nonce = self.storage.get_nonce(message_data['sender_pub_key'])
            if message_data['nonce'] <= last_nonce:
                logger.warning("Replay attack detected")
                return False
            
            # Update nonce
            self.storage.update_nonce(message_data['sender_pub_key'], message_data['nonce'])
            
            # Add to messages
            message_data['status'] = 'pending'
            self.storage.add_message(message_data)
            
            # Track seen message
            self.seen_messages.add(message_id)
            
            # Check if message is for us (if we have keys set)
            if self.keys and message_data.get('recipient_stealth') == self.keys['public_key']:
                logger.info("Message is for us! Adding to inbox")
                inbox_msg = {
                    'message_id': message_data['message_id'],
                    'sender_pub_key': message_data['sender_pub_key'],
                    'encrypted_text': message_data['encrypted_text'],
                    'ephemeral_public_key': message_data['ephemeral_public_key'],
                    'iv': message_data['iv'],
                    'timestamp': message_data['timestamp'],
                    'block_id': 'received',
                    'status': 'received'
                }
                
                if self.storage.add_to_inbox(inbox_msg):
                    logger.info(f"New message added to inbox: {message_data['message_id'][:8]}")
            
            return True
            
        except Exception as e:
            logger.error(f"Error receiving message: {e}")
            return False
    
    def _receive_block(self, block_data: Dict) -> bool:
        """Process received block"""
        try:
            block_id = block_data.get('block_id', 'unknown')
            logger.info(f"Processing received block: {block_id[:8]}")
            
            # Check if we've already seen this block
            if block_id in self.seen_blocks:
                logger.debug(f"Block {block_id[:8]} already seen, skipping")
                return True
            
            if not Block.validate_block(block_data):
                logger.warning("Invalid block received via HTTP")
                return False
            
            # Track seen block
            self.seen_blocks.add(block_id)
            
            if self.storage.add_block(block_data):
                for msg in block_data.get('messages', []):
                    self.storage.update_message_status(msg['message_id'], 'confirmed', block_data['block_id'])
                
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        asyncio.create_task(self.scan_for_messages(block_data))
                except RuntimeError:
                    pass
                
                logger.info(f"Block {block_data['block_id'][:8]} added via HTTP")
                return True
            
            return False
            
        except Exception as e:
            logger.error(f"Error receiving block: {e}")
            return False
    
    def _broadcast_message_http(self, message_data: Dict):
        """Broadcast message to all known peers via HTTP API"""
        peers = self.storage.get_peers()
        logger.info(f"Broadcasting message to {len(peers)} peers")
        
        for peer in peers:
            if peer['node_id'] != self.node_id:
                try:
                    url = f"http://{peer['address']}:{peer['api_port']}/api/receive_message"
                    response = requests.post(url, json=message_data, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"Message sent to {peer['node_id']}: {response.status_code}")
                    else:
                        logger.debug(f"Failed to send message to {peer['node_id']}: {response.status_code}")
                except Exception as e:
                    logger.debug(f"Could not send message to {peer['node_id']}: {e}")
    
    def _broadcast_block_http(self, block: Dict):
        """Broadcast block to all known peers via HTTP API"""
        peers = self.storage.get_peers()
        
        for peer in peers:
            if peer['node_id'] != self.node_id:
                try:
                    url = f"http://{peer['address']}:{peer['api_port']}/api/receive_block"
                    response = requests.post(url, json=block, timeout=5)
                    if response.status_code == 200:
                        logger.info(f"Block sent to {peer['node_id']}: {response.status_code}")
                    else:
                        logger.debug(f"Failed to send block to {peer['node_id']}: {response.status_code}")
                except Exception as e:
                    logger.debug(f"Could not send block to {peer['node_id']}: {e}")
    
    async def scan_for_messages(self, block: Dict):
        """Scan block for messages addressed to us"""
        if not self.keys:
            return
        
        for message in block.get('messages', []):
            try:
                if message.get('recipient_stealth') == self.keys['public_key']:
                    # Check if already in inbox
                    existing = any(m['message_id'] == message['message_id'] for m in self.storage.inbox)
                    if not existing:
                        inbox_msg = {
                            'message_id': message['message_id'],
                            'sender_pub_key': message.get('sender_pub_key', ''),
                            'encrypted_text': message.get('encrypted_text', ''),
                            'ephemeral_public_key': message.get('ephemeral_public_key', ''),
                            'iv': message.get('iv', ''),
                            'timestamp': message.get('timestamp', 0),
                            'block_id': block['block_id'],
                            'status': 'confirmed'
                        }
                        
                        if self.storage.add_to_inbox(inbox_msg):
                            logger.info(f"New message from block: {message['message_id'][:8]}")
            
            except Exception as e:
                logger.error(f"Error scanning message: {e}")
    
    def start(self):
        """Start the TitanMesh node"""
        # Load peers from CSV
        self._load_peers_from_csv()
        
        # Log initial state
        logger.info(f"Starting with {self.storage.get_block_count()} blocks, {self.storage.get_message_count()} messages")
        
        # Start P2P network in background
        def run_async_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            # Start P2P server
            loop.run_until_complete(self.p2p.start())
            
            # Now connect to peers after server is running
            loop.run_until_complete(self._connect_to_peers())
            
            loop.run_forever()
        
        p2p_thread = threading.Thread(target=run_async_loop, daemon=True)
        p2p_thread.start()
        
        # Start miner after sync
        def delayed_mining():
            time.sleep(10)
            logger.info("Starting miner after sync delay")
            self.miner.start_mining()
        
        mining_thread = threading.Thread(target=delayed_mining, daemon=True)
        mining_thread.start()
        
        # Schedule daily pruning
        def prune_daily():
            while True:
                time.sleep(86400)
                logger.info("Running daily block pruning...")
                self.storage.prune_old_blocks(30)
        
        prune_thread = threading.Thread(target=prune_daily, daemon=True)
        prune_thread.start()
        
        # Start web UI
        logger.info(f"=" * 60)
        logger.info(f"TitanMesh Messenger UI: http://localhost:{self.api_port}")
        logger.info(f"Node ID: {self.node_id}")
        logger.info(f"P2P Port: {self.port}")
        logger.info(f"API Port: {self.api_port}")
        logger.info(f"Blocks: {self.storage.get_block_count()}")
        logger.info(f"Messages: {self.storage.get_message_count()}")
        logger.info(f"=" * 60)
        logger.info("Key Management API:")
        logger.info(f"  POST /api/keys/generate - Generate new keypair")
        logger.info(f"  POST /api/keys/validate - Validate a private key")
        logger.info(f"  POST /api/keys/derive - Derive public key from private")
        logger.info(f"  POST /api/session/set_keys - Set keys for current session")
        logger.info(f"  POST /api/session/clear_keys - Clear session keys")
        logger.info(f"  GET  /api/session/status - Check session key status")
        logger.info(f"=" * 60)
        logger.info("IMPORTANT: Keys are NOT stored on the node!")
        logger.info("You must generate keys and set them in your session.")
        logger.info("=" * 60)
        
        self.app.run(host='0.0.0.0', port=self.api_port, debug=False, threaded=True)
    
    def _load_peers_from_csv(self):
        """Load peers from CSV file"""
        if not os.path.exists(self.peers_file):
            logger.warning(f"Peers file {self.peers_file} not found")
            self._create_default_peers_file()
            return
        
        with open(self.peers_file, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row['node_id'] != self.node_id:
                    self.storage.add_peer({
                        'node_id': row['node_id'],
                        'address': row['address'],
                        'port': int(row['port']),
                        'api_port': int(row['api_port'])
                    })
                    logger.info(f"Loaded peer: {row['node_id']} at {row['address']}:{row['api_port']}")
        
        logger.info(f"Loaded {len(self.storage.get_peers())} peers from CSV")
    
    def _create_default_peers_file(self):
        """Create a default peers CSV file"""
        default_peers = [
            {'node_id': 'node1', 'address': '127.0.0.1', 'port': '5000', 'api_port': '5001'},
            {'node_id': 'node2', 'address': '127.0.0.1', 'port': '5002', 'api_port': '5003'},
            {'node_id': 'node3', 'address': '127.0.0.1', 'port': '5004', 'api_port': '5005'},
        ]
        
        with open(self.peers_file, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=['node_id', 'address', 'port', 'api_port'])
            writer.writeheader()
            writer.writerows(default_peers)
        
        logger.info(f"Created default peers file: {self.peers_file}")
        
        for peer in default_peers:
            if peer['node_id'] != self.node_id:
                self.storage.add_peer({
                    'node_id': peer['node_id'],
                    'address': peer['address'],
                    'port': int(peer['port']),
                    'api_port': int(peer['api_port'])
                })
    
    async def _connect_to_peers(self):
        """Connect to all known peers"""
        peers = self.storage.get_peers()
        for peer in peers:
            if peer['node_id'] != self.node_id:
                asyncio.create_task(
                    self.p2p.connect_to_peer(peer['address'], peer['port'])
                )
        
        # After connecting, sync with peers
        await asyncio.sleep(3)
        await self._sync_with_peers()
    
    async def _sync_with_peers(self):
        """Sync blockchain with connected peers"""
        logger.info("=" * 40)
        logger.info("Starting sync with peers...")
        
        our_latest = self.storage.get_latest_block()
        our_height = our_latest['block_number'] if our_latest else -1
        logger.info(f"Our block height: {our_height}")
        
        peers = self.storage.get_peers()
        best_peer = None
        best_height = our_height
        
        for peer in peers:
            if peer['node_id'] != self.node_id:
                try:
                    url = f"http://{peer['address']}:{peer['api_port']}/api/status"
                    response = requests.get(url, timeout=3)
                    if response.status_code == 200:
                        status = response.json()
                        peer_height = status.get('latest_block', -1)
                        logger.info(f"Peer {peer['node_id']} block height: {peer_height}")
                        
                        if peer_height > best_height:
                            best_height = peer_height
                            best_peer = peer
                except Exception as e:
                    logger.debug(f"Could not reach {peer['node_id']}: {e}")
        
        if best_peer and best_height > our_height:
            logger.info(f"Syncing from {best_peer['node_id']} (height {best_height})")
            await self._download_blocks_from_peer(best_peer, our_height + 1, best_height)
        else:
            logger.info("Already synced or no better peer found")
        
        logger.info(f"Sync complete. Blocks: {self.storage.get_block_count()}")
        logger.info("=" * 40)
    
    async def _download_blocks_from_peer(self, peer: Dict, start_height: int, end_height: int):
        """Download blocks from a peer"""
        try:
            url = f"http://{peer['address']}:{peer['api_port']}/api/blocks?start={start_height}&end={end_height}"
            logger.info(f"Downloading blocks {start_height} to {end_height}")
            
            response = requests.get(url, timeout=30)
            
            if response.status_code == 200:
                data = response.json()
                blocks = data.get('blocks', [])
                logger.info(f"Downloaded {len(blocks)} blocks")
                
                for block_data in blocks:
                    if Block.validate_block(block_data):
                        if self.storage.add_block(block_data):
                            for msg in block_data.get('messages', []):
                                self.storage.update_message_status(msg['message_id'], 'confirmed', block_data['block_id'])
                            
                            await self.scan_for_messages(block_data)
                
                if len(blocks) > 0 and end_height > start_height + len(blocks) - 1:
                    new_start = start_height + len(blocks)
                    await self._download_blocks_from_peer(peer, new_start, end_height)
                
        except Exception as e:
            logger.error(f"Error downloading blocks: {e}")

# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point"""
    import argparse
    
    parser = argparse.ArgumentParser(description='TitanMesh Node')
    parser.add_argument('--port', type=int, default=5000, help='P2P port (default: 5000)')
    parser.add_argument('--peers', type=str, default='nodes.csv', help='Peers CSV file (default: nodes.csv)')
    parser.add_argument('--node-id', type=str, default=None, help='Node ID (default: auto-generated)')
    
    args = parser.parse_args()
    
    # Create and start node
    node = TitanNode(
        node_id=args.node_id,
        port=args.port,
        peers_file=args.peers
    )
    
    try:
        node.start()
    except KeyboardInterrupt:
        logger.info("Shutting down...")
        node.miner.stop_mining()
        node.storage.close()

if __name__ == '__main__':
    main()
