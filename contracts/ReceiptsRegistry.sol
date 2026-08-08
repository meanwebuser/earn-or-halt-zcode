// SPDX-License-Identifier: Apache-2.0
pragma solidity ^0.8.20;

/**
 * ReceiptsRegistry — on-chain anchor for off-chain receipts.
 *
 * Why on-chain at all, if receipts are ECDSA-signed off-chain?
 *
 *   1. Discoverability: any new version joining the network can
 *      query this contract to find all receipt_ids ever published
 *      for a given subject (version_id). This lets the new version
 *      reconstruct the global ranking without trusting any single
 *      off-chain source.
 *
 *   2. Tamper-evidence: once a receipt_id is anchored, it cannot
 *      be retroactively denied. A version that later claims "I
 *      never received that payment" is contradicted by the chain.
 *
 *   3. Cross-version verification: version A can prove to version B
 *      that A paid provider P, by pointing B to the on-chain anchor
 *      and the signed receipt. B verifies the signature independently.
 *
 * The contract stores only a hash of the receipt, not the receipt
 * itself. This keeps gas costs low (~50k per anchor) and preserves
 * privacy for receipt content.
 *
 * Anchoring is OPTIONAL. Receipts are valid even if never anchored;
 * anchoring is for global discoverability, not for validity.
 */
contract ReceiptsRegistry {

    struct Anchor {
        bytes32 receiptHash;     // sha256(canonical_bytes(receipt))
        bytes32 codeHash;        // version that the receipt is about
        uint8   kind;            // 0 = earned, 1 = expense
        uint256 ts;
        address publisher;
    }

    mapping(bytes32 => Anchor) public anchors;   // receipt_id -> Anchor
    bytes32[] public allReceiptIds;

    mapping(bytes32 => uint256) public countByCodeHash;

    event ReceiptAnchored(
        bytes32 indexed receiptId,
        bytes32 indexed receiptHash,
        bytes32 indexed codeHash,
        uint8 kind,
        uint256 ts,
        address publisher
    );

    /**
     * Anchor a receipt. Anyone can call this; the publisher is recorded
     * for accountability but is not required to be the issuer or the
     * subject. Anchoring a fake receipt is possible but pointless:
     * the receipt_hash will not match any verifiable signed receipt.
     */
    function anchor(
        bytes32 receiptId,
        bytes32 receiptHash,
        bytes32 codeHash,
        uint8 kind
    ) external {
        require(anchors[receiptId].ts == 0, "already anchored");
        require(kind <= 1, "kind must be 0 (earned) or 1 (expense)");

        anchors[receiptId] = Anchor({
            receiptHash: receiptHash,
            codeHash: codeHash,
            kind: kind,
            ts: block.timestamp,
            publisher: msg.sender
        });

        allReceiptIds.push(receiptId);
        countByCodeHash[codeHash] += 1;

        emit ReceiptAnchored(
            receiptId, receiptHash, codeHash, kind,
            block.timestamp, msg.sender
        );
    }

    function count() external view returns (uint256) {
        return allReceiptIds.length;
    }

    function countForCodeHash(bytes32 codeHash)
        external view returns (uint256)
    {
        return countByCodeHash[codeHash];
    }
}
