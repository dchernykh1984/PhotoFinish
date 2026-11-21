package com.dchernykh.photofinish.camera.capture

import com.dchernykh.photofinish.camera.pairing.Lens
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

private const val LAPTOP = "192.168.1.5"

class PriorityBoardTest {
    private val board = PriorityBoard()

    @Test
    fun `the first lens sends, the others wait while it is connected and behind`() {
        var behind = 5_000L
        var connected = true
        board.register(Lens.MAIN, LAPTOP, { connected }, { behind })
        board.register(Lens.TELEPHOTO, LAPTOP, { true }, { 60_000 })
        assertTrue(board.allows(Lens.MAIN, LAPTOP))
        assertFalse(board.allows(Lens.TELEPHOTO, LAPTOP))
        behind = PriorityBoard.BEHIND_MS
        assertTrue(board.allows(Lens.TELEPHOTO, LAPTOP))
        behind = 5_000
        connected = false // its laptop gone: it holds nobody back
        assertTrue(board.allows(Lens.TELEPHOTO, LAPTOP))
    }

    @Test
    fun `the first lens is the first of the referee's order that sends`() {
        board.order = listOf(Lens.TELEPHOTO, Lens.MAIN)
        board.register(Lens.MAIN, LAPTOP, { true }, { 9_000 })
        val off = board.register(Lens.TELEPHOTO, LAPTOP, { true }, { 9_000 })
        assertTrue(board.allows(Lens.TELEPHOTO, LAPTOP))
        assertFalse(board.allows(Lens.MAIN, LAPTOP))
        off()
        assertTrue(board.allows(Lens.MAIN, LAPTOP)) // the telephoto sends no more: the main is first
    }

    @Test
    fun `with no order of the referee's, the laptop's dialog's decides`() {
        board.order = emptyList()
        board.register(Lens.ULTRAWIDE, LAPTOP, { true }, { 0 })
        board.register(Lens.TELEPHOTO, LAPTOP, { true }, { 9_000 })
        assertFalse(board.allows(Lens.ULTRAWIDE, LAPTOP)) // the telephoto comes before it in the dialog
        assertTrue(board.allows(Lens.TELEPHOTO, LAPTOP))
    }

    @Test
    fun `a first lens sending to another laptop holds nobody back here`() {
        board.register(Lens.MAIN, "192.168.1.9", { true }, { 3_600_000 }) // kept for the laptop paired before
        board.register(Lens.MAIN, LAPTOP, { true }, { 0 })
        board.register(Lens.TELEPHOTO, LAPTOP, { true }, { 0 })
        assertTrue(board.allows(Lens.TELEPHOTO, LAPTOP))
        board.register(Lens.TELEPHOTO, "192.168.1.9", { true }, { 0 })
        assertFalse(board.allows(Lens.TELEPHOTO, "192.168.1.9")) // there, its first lens is behind
    }

    @Test
    fun `a lens of several senders waits while any of the first's is behind`() {
        board.register(Lens.MAIN, LAPTOP, { true }, { 0 })
        board.register(Lens.MAIN, LAPTOP, { true }, { 3_000 }) // what it kept before, sent alone
        board.register(Lens.FRONT, LAPTOP, { true }, { 0 })
        assertFalse(board.allows(Lens.FRONT, LAPTOP))
        assertTrue(PriorityBoard().allows(Lens.FRONT, LAPTOP)) // nobody sending: nobody waits
    }
}
