# TitanMesh - Decentralized PoW Messenger

A fully decentralized, peer-to-peer messaging protocol with built-in Proof-of-Work and end-to-end encryption. No central servers, no single point of failure.

## What is TitanMesh?

TitanMesh is a decentralized messaging system that operates without any central authority or server. Messages are transmitted directly between peers using a P2P network, secured with military-grade encryption, and verified through a lightweight Proof-of-Work mechanism.

Think of it as WhatsApp combined with Bitcoin features - the privacy of end-to-end encryption with the censorship resistance of blockchain technology.

## Key Features

End-to-End Encryption: AES-256-CBC with ECDH key exchange using SECP256k1 curve
Decentralized: No central servers, pure peer-to-peer network
Proof-of-Work: Anti-spam mechanism based on SHA-256
Blockchain Verification: Messages stored in immutable blocks
Client-Side Keys: Private keys never leave your device
Desktop Client: Modern PyQt6 GUI with dark theme
WebSocket P2P: Real-time communication between nodes
Local Storage: SQLite for messages, JSON for blockchain
Automatic Syncing: Peer discovery and blockchain synchronization

## Architecture

The system consists of three main layers:

1. Cryptography Layer: Handles key generation, encryption, decryption, and digital signatures using ECDSA and AES-256.

2. P2P Network Layer: Manages WebSocket connections between nodes, message broadcasting, and peer discovery.

3. Blockchain Layer: Creates blocks, validates Proof-of-Work, maintains the chain, and ensures message immutability.

Additional components include a Flask-based REST API for client communication, a PyQt6 desktop client for user interaction, and local storage for data persistence.

## Technology Stack

Backend (Node):
- Python 3.10+
- Flask - REST API and Web UI
- WebSockets - P2P communication
- ECDSA (SECP256k1) - Digital signatures
- AES-256-CBC - Message encryption
- SHA-256 - Hashing and Proof-of-Work
- Asyncio - Concurrent networking

Frontend (Client):
- PyQt6 - Desktop GUI
- SQLite - Local database
- Requests - HTTP communication

Cryptography Libraries (Pure Python):
- ecdsa - Elliptic curve cryptography
- pycryptodome - AES encryption
- hashlib - Hashing functions

## Installation

Clone the repository
cd titanmesh

Install dependencies:
pip install -r requirements.txt

Start the Node (Server):
python3 node.py --port 5000

Start the Client (GUI):
python3 titanmesh_client.py

## Quick Start Guide

Step 1: Run the Node
The node handles all network operations, blockchain validation, and message routing.
python3 node.py --port 5000

Step 2: Launch the Client
The client provides a desktop interface for sending and receiving messages.
python3 titanmesh_client.py

Step 3: Generate Your Keys
When you first launch the client, you will be prompted to generate a new keypair or import an existing one.

IMPORTANT: Your private key is stored locally only and never transmitted over the network.

Step 4: Start Messaging
Click New Conversation, enter the recipient's public key, and start sending encrypted messages.

## Security Model

Encryption Flow:
1. Key Generation: ECDSA keypair using SECP256k1 curve
2. Key Exchange: ECDH (Elliptic Curve Diffie-Hellman)
3. Symmetric Encryption: AES-256-CBC
4. Message Signing: ECDSA signatures
5. Anti-Spam: Proof-of-Work using SHA-256

Privacy Guarantees:
- End-to-End Encryption: Only sender and recipient can read messages
- Forward Secrecy: Each message uses ephemeral keys
- No Metadata Collection: No central server to log activity
- Client-Side Keys: Your private key never leaves your device
- Censorship Resistant: No central authority to block messages

## API Endpoints

Node API (HTTP):

/api/keys/generate - POST - Generate new keypair
/api/session/set_keys - POST - Set session keys
/api/send - POST - Send encrypted message
/api/inbox - GET - Get received messages
/api/sent - GET - Get sent messages
/api/message/<id> - GET - Get specific message
/api/status - GET - Node status
/api/peers - GET - List connected peers
/api/blocks - GET - Get blockchain data

P2P Protocol (WebSocket):

HANDSHAKE - Peer connection establishment
NEW_MESSAGE - Broadcast new message
NEW_BLOCK - Broadcast new block
REQUEST_SYNC - Request blockchain sync
REQUEST_PEERS - Request peer list

## Project Structure

titanmesh/
├── node.py                 # Main TitanMesh Node
├── titanmesh_client.py     # Desktop GUI Client
├── requirements.txt        # Python dependencies
├── nodes.csv              # Peer configuration
├── templates/
│   └── messenger.html     # Web UI template
├── static/                # Static assets
└── data/                  # Node data storage
    └── [node_id]/
        ├── blocks.json    # Blockchain storage
        ├── messages.json  # Message storage
        ├── inbox.json     # Inbox data
        ├── peers.json     # Peer list
        └── state.json     # Node state

## Performance Metrics

Message Encryption: Less than 10ms
PoW Solution (difficulty 4): Approximately 1-2 seconds
Block Creation: Approximately 5 seconds
Peer Discovery: Less than 1 second
Blockchain Sync: 100 blocks per second

## Use Cases

- Secure Communication for journalists, activists, and privacy-conscious users
- Corporate Messaging without third-party servers
- Censorship Resistance in regions with internet restrictions
- Web3 Integration for decentralized identity and messaging
- Education for learning blockchain, cryptography, and P2P networking

## Future Roadmap

- Mobile Apps for iOS and Android
- File Sharing with encrypted P2P file transfer
- Group Chats with multi-party encrypted conversations
- Light Clients with SPV for low-resource devices
- DHT Integration for better peer discovery
- Encrypted Voice and Video for real-time communication
- Token Integration for incentivized nodes

## Contributing

We welcome contributions. Here is how you can help:

1. Fork the repository
2. Create a feature branch: git checkout -b feature/amazing-feature
3. Commit your changes: git commit -m 'Add amazing feature'
4. Push to the branch: git push origin feature/amazing-feature
5. Open a Pull Request

Please ensure your code follows PEP 8 standards and includes appropriate documentation.

## Contact and Support

- Issues: GitHub Issues
- Telegram: @Xrisofenius

## Acknowledgments

- Bitcoin for inspiration on Proof-of-Work
- Signal Protocol for inspiration on end-to-end encryption
- IPFS for inspiration on decentralized networking
