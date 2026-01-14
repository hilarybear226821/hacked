#!/usr/bin/env python3
"""
Decoder Arbiter Tests - Confidence Fusion Verification

Tests all arbitration logic:
- Trust weighting
- Mutex filtering
- Evidence fusion
- Threshold decisions
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from modules.decoder_arbiter import DecoderArbiter, create_test_candidate

def test_single_decoder():
    """Test single decoder classification"""
    print("Test 1: Single Decoder Classification")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Submit high-confidence candidate
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.95, "frame1"))
    arbiter.finalize("frame1")
    
    assert len(emissions) == 1, "Should emit 1 classification"
    assert emissions[0]["protocol"] == "KeeLoq"
    assert emissions[0]["confidence"] >= 0.75
    
    print("✅ Single decoder works")
    return True

def test_consensus_fusion():
    """Test multiple decoders agreeing"""
    print("\nTest 2: Consensus Fusion")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Two decoders agree on KeeLoq
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.7, "frame2"))
    arbiter.submit(create_test_candidate("hcs301", "KeeLoq", 0.6, "frame2"))
    arbiter.finalize("frame2")
    
    assert len(emissions) == 1
    # Fused confidence should be higher than individual
    assert emissions[0]["confidence"] > 0.7
    assert len(emissions[0]["contributors"]) == 2
    
    print(f"✅ Fused confidence: {emissions[0]['confidence']:.2f}")
    return True

def test_mutex_filtering():
    """Test mutually exclusive protocol filtering"""
    print("\nTest 3: Mutex Filtering")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Competing protocols from mutex group
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.9, "frame3"))
    arbiter.submit(create_test_candidate("ev1527", "EV1527", 0.6, "frame3"))
    arbiter.finalize("frame3")
    
    assert len(emissions) == 1
    # Should keep KeeLoq (higher confidence)
    assert emissions[0]["protocol"] == "KeeLoq"
    
    print("✅ Mutex filtering works")
    return True

def test_threshold_rejection():
    """Test low-confidence rejection"""
    print("\nTest 4: Threshold Rejection")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Low confidence candidate
    arbiter.submit(create_test_candidate("princeton", "Princeton", 0.4, "frame4"))
    arbiter.finalize("frame4")
    
    assert len(emissions) == 0, "Should not emit low-confidence classification"
    
    stats = arbiter.get_stats()
    assert stats["discards"] == 1
    
    print("✅ Threshold rejection works")
    return True

def test_trust_weighting():
    """Test decoder trust weights"""
    print("\nTest 5: Trust Weighting")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # High-trust decoder
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.8, "frame5"))
    arbiter.finalize("frame5")
    
    conf1 = emissions[0]["confidence"] if emissions else 0
    
    emissions.clear()
    
    # Low-trust decoder with same raw confidence
    arbiter.submit(create_test_candidate("princeton", "Princeton", 0.8, "frame6"))
    arbiter.finalize("frame6")
    
    conf2 = emissions[0]["confidence"] if emissions else 0
    
    # KeeLoq (weight=1.0) should have higher adjusted confidence than Princeton (weight=0.7)
    assert conf1 > conf2, f"Trust weighting failed: {conf1} vs {conf2}"
    
    print(f"✅ Trust weighting: KeeLoq={conf1:.2f}, Princeton={conf2:.2f}")
    return True

def test_classification_types():
    """Test protocol type classification"""
    print("\nTest 6: Classification Types")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Rolling code
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.9, "frame7"))
    arbiter.finalize("frame7")
    
    assert emissions[0]["classification"] == "rolling_code"
    
    emissions.clear()
    
    # Fixed code
    arbiter.submit(create_test_candidate("ev1527", "EV1527", 0.9, "frame8"))
    arbiter.finalize("frame8")
    
    assert emissions[0]["classification"] == "fixed_code"
    
    print("✅ Classification types correct")
    return True

def test_statistics():
    """Test statistics tracking"""
    print("\nTest 7: Statistics Tracking")
    
    emissions = []
    arbiter = DecoderArbiter(lambda x: emissions.append(x))
    
    # Submit various candidates
    arbiter.submit(create_test_candidate("keeloq", "KeeLoq", 0.9, "frame9"))
    arbiter.submit(create_test_candidate("ev1527", "EV1527", 0.3, "frame10"))
    arbiter.finalize("frame9")
    arbiter.finalize("frame10")
    
    stats = arbiter.get_stats()
    
    assert stats["candidates_received"] == 2
    assert stats["frames_processed"] == 2
    assert stats["emissions"] == 1  # Only high-confidence emitted
    assert stats["discards"] == 1   # Low-confidence discarded
    
    print(f"✅ Stats: {stats}")
    return True

if __name__ == "__main__":
    print("=" * 60)
    print("Decoder Arbiter Test Suite")
    print("=" * 60 + "\n")
    
    tests = [
        ("Single Decoder", test_single_decoder),
        ("Consensus Fusion", test_consensus_fusion),
        ("Mutex Filtering", test_mutex_filtering),
        ("Threshold Rejection", test_threshold_rejection),
        ("Trust Weighting", test_trust_weighting),
        ("Classification Types", test_classification_types),
        ("Statistics", test_statistics),
    ]
    
    results = []
    for name, test_func in tests:
        try:
            passed = test_func()
            results.append((name, passed))
        except Exception as e:
            print(f"❌ {name} failed: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))
    
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)
    for name, passed in results:
        status = "✅ PASS" if passed else "❌ FAIL"
        print(f"{status}: {name}")
    
    all_passed = all(r[1] for r in results)
    print("\n" + "=" * 60)
    if all_passed:
        print("✅ ALL TESTS PASSED - Arbiter is production-ready")
    else:
        print("❌ SOME TESTS FAILED")
    print("=" * 60)
    
    sys.exit(0 if all_passed else 1)
