using System;
using System.ComponentModel.DataAnnotations;
using System.ComponentModel.DataAnnotations.Schema;

namespace WebApp.Models
{
    [Table("room_occupancy")]
    public class RoomOccupancy
    {
        [Key]
        [Column("occupancy_id")]
        public int OccupancyId { get; set; }

        [Column("room_id")]
        public int RoomId { get; set; }

        [Column("camera_id")]
        public int CameraId { get; set; }

        [Column("people_count")]
        public int PeopleCount { get; set; }

        [Column("timestamp")]
        public DateTime Timestamp { get; set; } = DateTime.UtcNow;

        // =========================
        // HELPER METHOD (NOT MAPPED)
        // =========================
        public bool IsOverCapacity(int maxCapacity)
        {
            return PeopleCount > maxCapacity;
        }
    }
}