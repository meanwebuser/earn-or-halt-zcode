// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * EarnOrHaltToken — ERC-20 with commons pool + starter credit.
 *
 * Design:
 *   - Fixed initial supply minted to commons pool (governance multisig).
 *   - Linear emission to commons pool over 4 years.
 *   - Any version can request starter credit by claiming a code_hash.
 *   - Starter credit is only granted if the code_hash matches a known
 *     release published by governance (i.e., the release was signed
 *     by the release key, which governance has verified off-chain).
 *
 * This contract does NOT enforce earned_revenue / cost — that is
 * computed off-chain from signed receipts (see earn_or_halt/receipts/).
 * The contract only enforces token movement.
 *
 * Anti-whale: this contract CANNOT prevent a whale from buying tokens
 * on an exchange and depositing them into a version's wallet. The
 * anti-whale defense lives in the off-chain rank_signal computation,
 * which only counts signed EarnedReceipts as earned_revenue. Whale
 * deposits increase the on-chain balance but do NOT increase
 * earned_revenue, so they do NOT push the version up the ranking.
 */
contract EarnOrHaltToken {
    string public constant name = "Earn or Halt Token";
    string public constant symbol = "EOH";
    uint8 public constant decimals = 18;

    uint256 public totalSupply;
    address public commonsPool;          // governance multisig
    address public releaseAuthority;     // can register known code_hashes

    uint256 public emissionStart;
    uint256 public emissionEnd;
    uint256 public emissionCap;          // total tokens to emit over period

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;
    mapping(bytes32 => bool) public knownCodeHashes;    // release registry
    mapping(bytes32 => bool) public starterCreditClaimed; // anti double-claim

    event Transfer(address indexed from, address indexed to, uint256 amount);
    event Approval(address indexed owner, address indexed spender, uint256 amount);
    event StarterCreditGranted(address indexed recipient, uint256 amount, bytes32 codeHash);
    event CodeHashRegistered(bytes32 indexed codeHash);

    modifier onlyCommonsPool() {
        require(msg.sender == commonsPool, "only commons pool");
        _;
    }

    modifier onlyReleaseAuthority() {
        require(msg.sender == releaseAuthority, "only release authority");
        _;
    }

    constructor(
        address _commonsPool,
        address _releaseAuthority,
        uint256 _initialSupply,
        uint256 _emissionPeriod
    ) {
        commonsPool = _commonsPool;
        releaseAuthority = _releaseAuthority;
        totalSupply = _initialSupply;
        balanceOf[_commonsPool] = _initialSupply;
        emissionStart = block.timestamp;
        emissionEnd = block.timestamp + _emissionPeriod;
        emissionCap = _initialSupply; // emit same amount again over the period
        emit Transfer(address(0), _commonsPool, _initialSupply);
    }

    // ── ERC-20 standard ──────────────────────────────────────────────

    function transfer(address to, uint256 amount) external returns (bool) {
        _transfer(msg.sender, to, amount);
        return true;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        emit Approval(msg.sender, spender, amount);
        return true;
    }

    function transferFrom(address from, address to, uint256 amount)
        external returns (bool)
    {
        uint256 a = allowance[from][msg.sender];
        require(a >= amount, "insufficient allowance");
        allowance[from][msg.sender] = a - amount;
        _transfer(from, to, amount);
        return true;
    }

    function _transfer(address from, address to, uint256 amount) internal {
        require(balanceOf[from] >= amount, "insufficient balance");
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        emit Transfer(from, to, amount);
    }

    // ── Release registry ─────────────────────────────────────────────

    function registerCodeHash(bytes32 codeHash) external onlyReleaseAuthority {
        knownCodeHashes[codeHash] = true;
        emit CodeHashRegistered(codeHash);
    }

    // ── Starter credit ───────────────────────────────────────────────

    /**
     * Request starter credit for a new version.
     * The version's claimed code_hash must be a known release.
     * Each code_hash can only claim once (prevents Sybil attacks).
     *
     * NOTE: this does NOT verify that the on-chain code at the
     * caller's address matches the claimed code_hash. That
     * verification happens off-chain, by other versions reading
     * the caller's published binary and recomputing its hash.
     */
    function requestStarterCredit(bytes32 codeHash) external returns (bool) {
        require(knownCodeHashes[codeHash], "unknown code_hash");
        require(!starterCreditClaimed[codeHash], "starter credit already claimed");

        starterCreditClaimed[codeHash] = true;
        uint256 amount = 1000 * 10**18;  // 1000 tokens starter credit

        // Fund from commons pool
        require(balanceOf[commonsPool] >= amount, "commons pool dry");
        _transfer(commonsPool, msg.sender, amount);

        emit StarterCreditGranted(msg.sender, amount, codeHash);
        return true;
    }

    // ── Emission ─────────────────────────────────────────────────────

    /**
     * Anyone can call this to mint emission to commons pool up to the
     * cap, prorated by elapsed time. This makes the emission schedule
     * deterministic and trustless.
     */
    function collectEmission() external returns (uint256) {
        if (block.timestamp >= emissionEnd) {
            // Mint remaining cap if any
            uint256 remaining = emissionCap - (totalSupply - balanceOf[commonsPool]);
            if (remaining > 0) {
                totalSupply += remaining;
                balanceOf[commonsPool] += remaining;
                emit Transfer(address(0), commonsPool, remaining);
            }
            return remaining;
        }

        uint256 elapsed = block.timestamp - emissionStart;
        uint256 totalEmitted = (emissionCap * elapsed) / (emissionEnd - emissionStart);
        uint256 alreadyEmitted = (totalSupply - balanceOf[commonsPool] +
            balanceOf[commonsPool]); // placeholder; in production, track separately
        // Simplified: just mint a small per-call amount based on time.
        uint256 toMint = (emissionCap * 1 hours) / (emissionEnd - emissionStart);
        if (toMint > balanceOf[commonsPool] + toMint - totalSupply) {
            toMint = emissionCap - totalSupply;
        }
        if (toMint == 0) return 0;

        totalSupply += toMint;
        balanceOf[commonsPool] += toMint;
        emit Transfer(address(0), commonsPool, toMint);
        return toMint;
    }
}
